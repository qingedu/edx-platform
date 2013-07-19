from django.db import models
from xmodule.modulestore.django import modulestore
from xmodule.modulestore import Location
from contentstore.views.preview import get_preview_module
from mitxmako.shortcuts import render_to_string
import pickle


class ContentTest(models.Model):
    """
    Model for a user-created test for a capa-problem
    """

    # the problem to test (location)
    # future-proof against long locations?
    problem_location = models.CharField(max_length=100)

    # what the problem should evaluate as (correct or incorrect)
    # TODO: make this a dict of correctness for each input
    should_be = models.CharField(max_length=20)

    # the current state of the test
    verdict = models.TextField()

    # pickle of dictionary that is the stored input
    response_dict = models.TextField()

    # messeges for verdict
    ERROR = "ERROR"
    PASS = "Pass"
    FAIL = "Fail"
    NONE = "Not Run"

    def __init__(self, *arg, **kwargs):
        """
        Overwrite default __init__ behavior to pickle the dictionary and
            save in a new field so we know if the response_dict gets overwritten
        """

        if 'response_dict' not in kwargs:
            kwargs['response_dict'] = {}

        kwargs['response_dict'] = pickle.dumps(kwargs['response_dict'])
        super(ContentTest, self).__init__(*arg, **kwargs)

        # store the old dict for later comparison (only update if it is changed)
        self._old_response_dict = self.response_dict

    @property
    def capa_problem(self):
        # create a preview capa problem
        lcp = self.capa_module().lcp

        from lxml import etree

        # override html methods
        for key in lcp.responders:

            # define wrapper
            def wrapper(func):
                def html_wrapper(*args, **kwargs):

                    # make surrounding div for each response
                    div = etree.Element('div')
                    div.set('class', "verdict-response-wrapper")

                    # should_be choice for this response
                    buttons = etree.fromstring(self._should_be_buttons(self.should_be))

                    div.append(func(*args, **kwargs))
                    div.append(buttons)
                    return div

                return html_wrapper

            # execute the override
            lcp.responders[key].render_html = wrapper(lcp.responders[key].render_html)

        return lcp

    def capa_module(self):
        # create a preview of the capa_module
        problem_descriptor = modulestore().get_item(Location(self.problem_location))
        preview_module = get_preview_module(0, problem_descriptor)

        # edit the module to have the correct test-student-responses
        # and (in the future support randomization)
        new_lcp_state = preview_module.get_state_for_lcp()
        new_lcp_state['student_answers'] = self._get_response_dictionary()
        preview_module.lcp = preview_module.new_lcp(new_lcp_state)
        return preview_module

    def save(self, *arg, **kwargs):
        """
        Overwrite default save behavior with the following features:
            > If the children haven't been created, create them
            > If the response dictionary is being changed, update the children
        """

        # if we are changing something, reset verdict by default
        if not('dont_reset' in kwargs):
            self.verdict = self.NONE
        else:
            kwargs.pop('dont_reset')

        # if we have a dictionary
        # import nose; nose.tools.set_trace()
        if hasattr(self, 'response_dict'):
            #if it isn't pickled, pickle it.
            if not(isinstance(self.response_dict, basestring)):
                self.response_dict = pickle.dumps(self.response_dict)

                # if it is new, update children
                if self.response_dict != self._old_response_dict:
                    self._update_dictionary(pickle.loads(self.response_dict))

        # save it as normal
        super(ContentTest, self).save(*arg, **kwargs)

        # look for children
        children = Response.objects.filter(content_test=self.pk)

        # if there are none, try to create them
        if children.count() == 0:
            self._create_children()

    def run(self):
        '''run the test, and see if it passes'''

        # process dictionary that is the response from grading
        grade_dict = self._evaluate(self._get_response_dictionary())

        # compare the result with what is should be
        self.verdict = self._make_verdict(grade_dict)

        # write the change to the database and return the result
        self.save(dont_reset=True)
        return self.verdict

    def get_html_summary(self):
        """
        return an html summary of this test
        """

        # retrieve all inputs sorted first by response, and then by order in that response
        sorted_inputs = self.input_set.order_by('response_index', 'input_index').values('answer')
        answers = [input_model['answer'] for input_model in sorted_inputs]

        # construct a context for rendering this
        context = {'answers': answers, 'verdict': self.verdict, 'should_be': self.should_be}
        return render_to_string('content_testing/unit_summary.html', context)

    def get_html_form(self):
        """
        return html to put into form for editing and creating
        """

        # THIS FUNCTION IS BASICALLY A COMPLETE HACK

        # html with the inputs blank
        html_form = self.capa_problem.get_html()

        # remove any forms that the html has
        import re
        remove_form_open = r"(<form)[^>]*>"
        remove_form_close = r"(/form)"
        html_form = re.sub(remove_form_open, '', html_form)
        html_form = re.sub(remove_form_close, '', html_form)

        # add the radio buttons
        html_form = html_form + self._should_be_buttons(self.should_be)
        return html_form

#======= Private Methods =======#

    def _should_be_buttons(self, resp_should_be):
        """
        given an individual should_be, generate the appropriate radio buttons
        """

        # default to filling in the correct bubble
        context = {
            "check_correct": "checked=\"True\"",
            "check_incorrect": "",
            "check_error": ""
        }

        if resp_should_be.lower() == "incorrect":
            context = {
                "check_correct": "",
                "check_incorrect": "checked=\"True\"",
                "check_error": ""
            }
        elif resp_should_be.lower() == "error":
            context = {
                "check_correct": "",
                "check_incorrect": "",
                "check_error": "checked=\"True\""
            }

        string = render_to_string('content_testing/form_bottom.html', context)
        fp = open('/Users/irh/Desktop/out.txt', 'w')
        fp.write(string)
        fp.close()

        return render_to_string('content_testing/form_bottom.html', context)

    def _evaluate(self, response_dict):
        """
        Give the capa_problem the response dictionary and return the result
        """

        # instantiate the capa problem so it can grade itself
        capa = self.capa_problem
        try:
            grade_dict = capa.grade_answers(response_dict)
            return grade_dict
        except:
            return None

    def _make_verdict(self, correct_map):
        """
        compare what the result of the grading should be with the actual grading
        and return the verdict
        """

        # if there was an error
        if correct_map is None:
            # if we want error, return pass
            if self.should_be == self.ERROR:
                return self.PASS
            return self.ERROR

        # this will all change because self.shuold_be will become a dictionary!!
        passing_all = True
        for grade in correct_map.get_dict().values():
            if grade['correctness'] == 'incorrect':
                passing_all = False
                break

        if (self.should_be.lower() == 'correct' and passing_all) or (self.should_be.lower() == 'incorrect' and not(passing_all)):
            return self.PASS
        else:
            return self.FAIL

    def _get_response_dictionary(self):
        """
        create dictionary to be submitted to the grading function
        """

        # assume integrity has been maintained!!
        resp_dict = self.response_dict

        # unpickle if necessary
        if isinstance(resp_dict, basestring):
            resp_dict = pickle.loads(resp_dict)
        
        return resp_dict

    def _get_dict_from_children(self):
        """
        build the response dictionary by getting the values from the children
        """

        resp_dict = {}
        for resp_model in self.response_set.all():
            for input_model in resp_model.input_set.all():
                resp_dict[input_model.string_id] = input_model.answer

        return resp_dict

    def _create_children(self):
        '''create child responses and input entries when created'''

        # create a preview capa problem
        problem_capa = self.capa_problem

        # go through responder objects
        for responder_xml, responder in problem_capa.responders.iteritems():

            # put the response object in the database
            response_model = Response.objects.create(
                content_test=self,
                xml=responder_xml,
                string_id=responder.id)

            # tell it to put its children in the database
            response_model._create_children(responder, pickle.loads(self.response_dict))

    def _update_dictionary(self, new_dict):
        '''update the input models with the new responses'''

        for resp_model in self.response_set.all():
            for input_model in resp_model.input_set.all():
                input_model.answer = new_dict[input_model.string_id]
                input_model.save()


class Response(models.Model):
    '''Object that corresponds to the <_____response> fields'''

    # the tests in which this response resides
    content_test = models.ForeignKey(ContentTest)

    # the string identifier
    string_id = models.CharField(max_length=100, editable=False)

    # the inner xml of this response (used to extract the object quickly (ideally))
    xml = models.TextField(editable=False)

    def _create_children(self, resp_obj=None, response_dict={}):
        '''generate the database entries for the inputs to this response'''

        # see if we need to construct the object from database
        if resp_obj is None:
            resp_obj = self.capa_response

        # go through inputs in this response object
        for entry in resp_obj.inputfields:
            # create the input models
            Input.objects.create(
                response=self,
                content_test=self.content_test,
                string_id=entry.attrib['id'],
                response_index=entry.attrib['response_id'],
                input_index=entry.attrib['answer_id'],
                answer=response_dict.get(entry.attrib['id'], ''))

    @property
    def capa_response(self):
        '''get the capa-response object to which this response model corresponds'''
        parent_capa = self.content_test.capa_problem

        # the obvious way doesn't work :(
        # return parent_capa.responders[self.xml]

        self_capa = None
        for responder in parent_capa.responders.values():
            if responder.id == self.string_id:
                self_capa = responder
                break

        if self_capa is None:
            raise LookupError

        return self_capa


class Input(models.Model):
    '''the input to a Response'''

    # The response in which this input lives
    response = models.ForeignKey(Response)

    # The test in which this input resides (grandchild)
    content_test = models.ForeignKey(ContentTest)

    # sequence (first response field, second, etc)
    string_id = models.CharField(max_length=100, editable=False)

    # number for the response that this input is in
    response_index = models.PositiveSmallIntegerField()

    # number for the place this input is in the response
    input_index = models.PositiveSmallIntegerField()

    # the input, supposed a string
    answer = models.CharField(max_length=50, blank=True)
