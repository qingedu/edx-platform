window.TabsEditingDescriptorModel =
  add_save : (id, tab_name, save_function) ->
    ###
    Function that register save functions of every tab.
    ###
    @init(id)
    @[id].model_update[tab_name] = save_function

  add_onswitch : (id, tab_name, onswitch_function) ->
    ###
    Function that register functions invoked when switching
    to particular tab.
    ###
    @init(id)
    @[id].tab_switch[tab_name] = onswitch_function

  update_value : (id, tab_name) ->
    ###
    Function that invokes when switching tabs.
    It ensures that data from previous tab is stored.
    If new tab need this data, it should retrieve it from 
    stored value.
    ###
    @init(id)
    @[id]['value'] = @[id]['model_update'][tab_name]()  if $.isFunction(@[id]['model_update'][tab_name])

  get_value : (id, tab_name) ->
    ### 
    Retrieves stored data on save.
    1. When we switching tabs - previous tab data is always saved to @[id].value
    2. If current tab have registered save method, it should be invoked 1st.
    (If we have edited in 1st tab, then switched to 2nd, 2nd tab should
    care about getting data from @[id].value somehow.)
    ###
    @init(id)
    if $.isFunction(@[id]['model_update'][tab_name])
      @[id]['model_update'][tab_name]() 
    else
      if typeof @[id]['value'] is 'undefined'
        return null
      else
        return @[id]['value']

  init : (id) ->
    ###
    Initialize objects per id.
    Id is html_id of descriptor.
    ###
    @[id] = @[id] or {}
    @[id].tab_switch = @[id]['tab_switch'] or {}
    @[id].model_update = @[id]['model_update'] or {}


class @TabsEditingDescriptor
  @isInactiveClass : "is-inactive"

  constructor: (element) ->
    @element = element;
    ###
    Does not tested on syncing of multiple editors of same type in tabs
    (Like many CodeMirrors)
    ###

    $('.component-edit-header').hide()

    @$tabs = $(".tab", @element)
    @$content = $(".component-tab", @element)

    @element.find('.editor-tabs .tab').each (index, value) =>
      $(value).on('click', @onSwitchEditor)

    # If default visible tab is not setted or if were marked as current
    # more than 1 tab just first tab will be shown
    currentTab = @$tabs.filter('.current')
    currentTab = @$tabs.first() if currentTab.length isnt 1
    @html_id = @$tabs.closest('.wrapper-comp-editor').data('html_id')
    currentTab.trigger("click", [true, @html_id])
    
  onSwitchEditor: (e, firstTime, html_id) =>
    e.preventDefault();

    isInactiveClass = TabsEditingDescriptor.isInactiveClass
    $currentTarget = $(e.currentTarget)

    # hide old bar 
    editorModeButton =  @element.find('#editor-mode').find("a")
    editorModeButton.removeClass('is-set')
    # and set metadata editor to active, it will be shown by tab engine
    settingsEditor = @element.find('.wrapper-comp-settings')
    settingsModeButton = @element.find('#settings-mode').find("a")
    settingsEditor.addClass('is-active')
    settingsModeButton.addClass('is-set')

    if not $currentTarget.hasClass('current') or firstTime is true

      previousTab = null

      @$tabs.each( (index, value) ->
        if $(value).hasClass('current')
          previousTab = $(value).html()
      )

      # init and save data from previous tab
      window.TabsEditingDescriptorModel.init(@html_id)
      window.TabsEditingDescriptorModel.update_value(@html_id, previousTab)

      # save data from editor in previous tab to editor in current tab here.

      # call onswitch
      if $.isFunction(window.TabsEditingDescriptorModel[@html_id].tab_switch[$currentTarget.text()])
        window.TabsEditingDescriptorModel[@html_id].tab_switch[$currentTarget.text()]()

      @$tabs.removeClass('current')
      $currentTarget.addClass('current')

      # Tabs are implemeted like anchors. Therefore we can use hash to find
      # corresponding content
      content_id = $currentTarget.attr('href')

      @$content
        .addClass(isInactiveClass)
        .filter(content_id)
        .removeClass(isInactiveClass)

  save: ->
    @element.off('click', '.editor-tabs .tab', @onSwitchEditor)
    current_tab = @$tabs.filter('.current').html()
    data: window.TabsEditingDescriptorModel.get_value(@html_id, current_tab)
