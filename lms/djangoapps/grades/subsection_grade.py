"""
SubsectionGrade Class
"""
from abc import ABCMeta
from collections import OrderedDict
from logging import getLogger

from lazy import lazy

from lms.djangoapps.grades.models import BlockRecord, PersistentSubsectionGrade
from lms.djangoapps.grades.scores import get_score, possibly_scored
from xmodule import block_metadata_utils, graders
from xmodule.graders import AggregatedScore, ShowCorrectness


log = getLogger(__name__)


class SubsectionGradeBase(object):
    """
    Abstract base class for Subsection Grades.
    """
    __metaclass__ = ABCMeta

    def __init__(self, subsection):
        self.location = subsection.location
        self.display_name = block_metadata_utils.display_name_with_default_escaped(subsection)
        self.url_name = block_metadata_utils.url_name_for_block(subsection)

        self.format = getattr(subsection, 'format', '')
        self.due = getattr(subsection, 'due', None)
        self.graded = getattr(subsection, 'graded', False)
        self.show_correctness = getattr(subsection, 'show_correctness', '')

        self.course_version = getattr(subsection, 'course_version', None)
        self.subtree_edited_timestamp = getattr(subsection, 'subtree_edited_on', None)

        self.override = None

    @property
    def attempted(self):
        """
        Returns whether any problem in this subsection
        was attempted by the student.
        """

        assert self.all_total is not None, (
            "SubsectionGrade not fully populated yet.  Call init_from_structure or init_from_model "
            "before use."
        )
        return self.all_total.attempted

    def show_grades(self, has_staff_access):
        """
        Returns whether subsection scores are currently available to users with or without staff access.
        """
        return ShowCorrectness.correctness_available(self.show_correctness, self.due, has_staff_access)

    @property
    def attempted_graded(self):
        """
        Returns whether the user had attempted a graded problem in this subsection.
        """
        raise NotImplementedError

    @property
    def percent_graded(self):
        """
        Returns the percent score of the graded problems in this subsection.
        """
        raise NotImplementedError


class ZeroSubsectionGrade(SubsectionGradeBase):
    """
    Class for Subsection Grades with Zero values.
    """

    def __init__(self, subsection, course_data):
        super(ZeroSubsectionGrade, self).__init__(subsection)
        self.course_data = course_data

    @property
    def attempted_graded(self):
        return False

    @property
    def percent_graded(self):
        return 0.0

    @property
    def all_total(self):
        return self._aggregate_scores[0]

    @property
    def graded_total(self):
        return self._aggregate_scores[1]

    @lazy
    def _aggregate_scores(self):
        return graders.aggregate_scores(self.problem_scores.values())

    @lazy
    def problem_scores(self):
        """
        Overrides the problem_scores member variable in order
        to return empty scores for all scorable problems in the
        course.
        """
        locations = OrderedDict()  # dict of problem locations to ProblemScore
        for block_key in self.course_data.structure.post_order_traversal(
                filter_func=possibly_scored,
                start_node=self.location,
        ):
            block = self.course_data.structure[block_key]
            if getattr(block, 'has_score', False):
                problem_score = get_score(
                    submissions_scores={}, csm_scores={}, persisted_block=None, block=block,
                )
                if problem_score is not None:
                    locations[block_key] = problem_score
        return locations


class NonZeroSubsectionGrade(SubsectionGradeBase):
    """
    Abstract base class for Subsection Grades with
    possibly NonZero values.
    """
    __metaclass__ = ABCMeta

    def __init__(self, subsection, all_total, graded_total, override=None):
        super(NonZeroSubsectionGrade, self).__init__(subsection)
        self.all_total = all_total
        self.graded_total = graded_total
        self.override = override

    @property
    def attempted_graded(self):
        return self.graded_total.first_attempted is not None

    @property
    def percent_graded(self):
        if self.graded_total.possible > 0:
            return self.graded_total.earned / self.graded_total.possible
        else:
            return 0.0

    @staticmethod
    def _compute_block_score(
            block_key,
            course_structure,
            submissions_scores,
            csm_scores,
            persisted_block=None,
    ):
        try:
            block = course_structure[block_key]
        except KeyError:
            # It's possible that the user's access to that
            # block has changed since the subsection grade
            # was last persisted.
            pass
        else:
            if getattr(block, 'has_score', False):
                return get_score(
                    submissions_scores,
                    csm_scores,
                    persisted_block,
                    block,
                )


class ReadSubsectionGrade(NonZeroSubsectionGrade):
    """
    Class for Subsection grades that are read from the database.
    """
    def __init__(self, subsection, model, factory):
        all_total = AggregatedScore(
            tw_earned=model.earned_all,
            tw_possible=model.possible_all,
            graded=False,
            first_attempted=model.first_attempted,
        )
        graded_total = AggregatedScore(
            tw_earned=model.earned_graded,
            tw_possible=model.possible_graded,
            graded=True,
            first_attempted=model.first_attempted,
        )
        override = model.override if hasattr(model, 'override') else None

        # save these for later since we compute problem_scores lazily
        self.model = model
        self.factory = factory

        super(ReadSubsectionGrade, self).__init__(subsection, all_total, graded_total, override)

    @lazy
    def problem_scores(self):
        problem_scores = OrderedDict()
        for block in self.model.visible_blocks.blocks:
            problem_score = self._compute_block_score(
                block.locator,
                self.factory.course_data.structure,
                self.factory._submissions_scores,
                self.factory._csm_scores,
                block,
            )
            if problem_score:
                problem_scores[block.locator] = problem_score
        return problem_scores


class CreateSubsectionGrade(NonZeroSubsectionGrade):
    """
    Class for Subsection grades that are newly created or updated.
    """
    def __init__(self, subsection, course_structure, submissions_scores, csm_scores):
        self.problem_scores = OrderedDict()
        for block_key in course_structure.post_order_traversal(
                filter_func=possibly_scored,
                start_node=subsection.location,
        ):
            problem_score = self._compute_block_score(block_key, course_structure, submissions_scores, csm_scores)
            if problem_score:
                self.problem_scores[block_key] = problem_score

        all_total, graded_total = graders.aggregate_scores(self.problem_scores.values())

        super(CreateSubsectionGrade, self).__init__(subsection, all_total, graded_total)

    def update_or_create_model(self, student, score_deleted=False):
        """
        Saves or updates the subsection grade in a persisted model.
        """
        if self._should_persist_per_attempted(score_deleted):
            return PersistentSubsectionGrade.update_or_create_grade(**self._persisted_model_params(student))

    @classmethod
    def bulk_create_models(cls, student, subsection_grades, course_key):
        """
        Saves the subsection grade in a persisted model.
        """
        params = [
            subsection_grade._persisted_model_params(student)  # pylint: disable=protected-access
            for subsection_grade in subsection_grades
            if subsection_grade
            if subsection_grade._should_persist_per_attempted()  # pylint: disable=protected-access
        ]
        return PersistentSubsectionGrade.bulk_create_grades(params, student.id, course_key)

    def _should_persist_per_attempted(self, score_deleted=False):
        """
        Returns whether the SubsectionGrade's model should be
        persisted based on settings and attempted status.

        If the learner's score was just deleted, they will have
        no attempts but the grade should still be persisted.
        """
        return (
            self.all_total.first_attempted is not None or
            score_deleted
        )

    def _persisted_model_params(self, student):
        """
        Returns the parameters for creating/updating the
        persisted model for this subsection grade.
        """
        return dict(
            user_id=student.id,
            usage_key=self.location,
            course_version=self.course_version,
            subtree_edited_timestamp=self.subtree_edited_timestamp,
            earned_all=self.all_total.earned,
            possible_all=self.all_total.possible,
            earned_graded=self.graded_total.earned,
            possible_graded=self.graded_total.possible,
            visible_blocks=self._get_visible_blocks,
            first_attempted=self.all_total.first_attempted,
        )

    @property
    def _get_visible_blocks(self):
        """
        Returns the list of visible blocks.
        """
        return [
            BlockRecord(location, score.weight, score.raw_possible, score.graded)
            for location, score in
            self.problem_scores.iteritems()
        ]
