# -*- coding: utf-8 -*-
from Tools.Profile import profile
from Screen import Screen
import Screens.InfoBar
import Components.ParentalControl
from Components.Button import Button
from Components.Renderer.Picon import getPiconName
from Components.ServiceList import ServiceList, refreshServiceList
from Components.ActionMap import NumberActionMap, ActionMap, HelpableActionMap
from Components.MenuList import MenuList
from Components.ServiceEventTracker import ServiceEventTracker, InfoBarBase
profile('ChannelSelection.py 1')
from EpgSelection import EPGSelection
from enigma import eServiceReference, eEPGCache, eServiceCenter, eRCInput, eTimer, eDVBDB, iPlayableService, iServiceInformation, getPrevAsciiCode, eEnv, loadPNG
from Components.config import config, configfile, ConfigSubsection, ConfigText, ConfigYesNo
from Tools.NumericalTextInput import NumericalTextInput
profile('ChannelSelection.py 2')
from Components.NimManager import nimmanager
profile('ChannelSelection.py 2.1')
from Components.Sources.RdsDecoder import RdsDecoder
profile('ChannelSelection.py 2.2')
from Components.Sources.ServiceEvent import ServiceEvent
from Components.Sources.Event import Event
profile('ChannelSelection.py 2.3')
from Components.Input import Input
profile('ChannelSelection.py 3')
from Components.ChoiceList import ChoiceList, ChoiceEntryComponent
from Components.SystemInfo import SystemInfo
from Screens.InputBox import PinInput
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Screens.MessageBox import MessageBox
from Screens.ServiceInfo import ServiceInfo
from Screens.Hotkey import InfoBarHotkey, hotkeyActionMap, getHotkeyFunctions
profile('ChannelSelection.py 4')
from Screens.PictureInPicture import PictureInPicture
from Components.Sources.List import List
from Screens.RdsDisplay import RassInteractive
from ServiceReference import ServiceReference
from Tools.BoundFunction import boundFunction
from Tools import Notifications
from Tools.Alternatives import CompareWithAlternatives, GetWithAlternative
from Tools.Directories import fileExists
from time import localtime, time
from Plugins.Plugin import PluginDescriptor
from Components.PluginComponent import plugins
from Screens.ChoiceBox import ChoiceBox
from Screens.EventView import EventViewEPGSelect
import os, unicodedata
profile('ChannelSelection.py after imports')
FLAG_SERVICE_NEW_FOUND = 64
FLAG_IS_DEDICATED_3D = 128
FLAG_HIDE_VBI = 512
FLAG_CENTER_DVB_SUBS = 2048 #define in lib/dvb/idvb.h as dxNewFound = 64 and dxIsDedicated3D = 128

class BouquetSelector(Screen):

    def __init__(self, session, bouquets, selectedFunc, enableWrapAround = True):
        Screen.__init__(self, session)
        self.setTitle(_('Choose bouquet'))
        self.selectedFunc = selectedFunc
        self['actions'] = ActionMap(['OkCancelActions'], {'ok': self.okbuttonClick,
         'cancel': self.cancelClick})
        entrys = [ (x[0], x[1]) for x in bouquets ]
        self['menu'] = MenuList(entrys, enableWrapAround)

    def getCurrent(self):
        cur = self['menu'].getCurrent()
        return cur and cur[1]

    def okbuttonClick(self):
        self.selectedFunc(self.getCurrent())

    def up(self):
        self['menu'].up()

    def down(self):
        self['menu'].down()

    def cancelClick(self):
        self.close(False)


class SilentBouquetSelector():

    def __init__(self, bouquets, enableWrapAround = False, current = 0):
        self.bouquets = [ b[1] for b in bouquets ]
        self.pos = current
        self.count = len(bouquets)
        self.enableWrapAround = enableWrapAround

    def up(self):
        if self.pos > 0 or self.enableWrapAround:
            self.pos = (self.pos - 1) % self.count

    def down(self):
        if self.pos < self.count - 1 or self.enableWrapAround:
            self.pos = (self.pos + 1) % self.count

    def getCurrent(self):
        return self.bouquets[self.pos]


OFF = 0
EDIT_BOUQUET = 1
EDIT_ALTERNATIVES = 2

def append_when_current_valid(current, menu, args, level = 0, key = ''):
    if current and current.valid() and level <= config.usage.setup_level.index:
        menu.append(ChoiceEntryComponent(key, args))


def removed_userbouquets_available():
    for file in os.listdir('/etc/enigma2/'):
        if file.startswith('userbouquet') and file.endswith('.del'):
            return True

    return False


class ChannelContextMenu(Screen):

    def __init__(self, session, csel):
        Screen.__init__(self, session)
	self.setTitle(_("Channel context menu"))
        self.csel = csel
        self.bsel = None
        if self.isProtected():
            self.onFirstExecBegin.append(boundFunction(self.session.openWithCallback, self.protectResult, PinInput, pinList=[ x.value for x in config.ParentalControl.servicepin ], triesEntry=config.ParentalControl.retries.servicepin, title=_('Please enter the correct pin code'), windowTitle=_('Enter pin code')))
        self['actions'] = ActionMap(['OkCancelActions',
         'ColorActions',
         'NumberActions',
         'MenuActions'], {'ok': self.okbuttonClick,
         'cancel': self.cancelClick,
         'blue': self.showServiceInPiP,
         'red': self.playMain,
         'menu': self.openSetup,
     '1': self.unhideParentalServices,
         '2': self.renameEntry,
         '3': self.findCurrentlyPlayed,
         '5': self.addServiceToBouquetOrAlternative,
         '6': self.toggleMoveModeSelect,
         '8': self.removeEntry})
        menu = []
        self.removeFunction = False
        self.addFunction = False
        self.PiPAvailable = False
        current = csel.getCurrentSelection()
        current_root = csel.getRoot()
        current_sel_path = current.getPath()
        current_sel_flags = current.flags
        inBouquetRootList = current_root and 'FROM BOUQUET "bouquets.' in current_root.getPath()
        inAlternativeList = current_root and 'FROM BOUQUET "alternatives' in current_root.getPath()
        self.inBouquet = csel.getMutableList() is not None
        haveBouquets = config.usage.multibouquet.value
        from Components.ParentalControl import parentalControl
        self.parentalControl = parentalControl
        self.parentalControlEnabled = config.ParentalControl.servicepin[0].value and config.ParentalControl.servicepinactive.value
        if not (current_sel_path or current_sel_flags & (eServiceReference.isDirectory | eServiceReference.isMarker)) or current_sel_flags & eServiceReference.isGroup:
            append_when_current_valid(current, menu, (_('show transponder info'), self.showServiceInformations), level=2)
        if csel.bouquet_mark_edit == OFF and not csel.entry_marked:
            if not inBouquetRootList:
                isPlayable = not current_sel_flags & (eServiceReference.isMarker | eServiceReference.isDirectory)
                if isPlayable:
                    for p in plugins.getPlugins(PluginDescriptor.WHERE_CHANNEL_CONTEXT_MENU):
                        append_when_current_valid(current, menu, (p.name, boundFunction(self.runPlugin, p)), key='bullet')

                    if config.servicelist.startupservice.value == current.toString():
                        append_when_current_valid(current, menu, (_('stop using as startup service'), self.unsetStartupService), level=0)
                    else:
                        append_when_current_valid(current, menu, (_('set as startup service'), self.setStartupService), level=0)
                    if self.parentalControlEnabled:
                        if self.parentalControl.getProtectionLevel(current.toCompareString()) == -1:
                            append_when_current_valid(current, menu, (_('add to parental protection'), boundFunction(self.addParentalProtection, current)), level=0)
                        elif self.parentalControl.isServiceProtectionBouquet(current.toCompareString()):
                            append_when_current_valid(current, menu, (_('service is in bouquet parental protection'), self.cancelClick), level=0)
                        else:
                            append_when_current_valid(current, menu, (_('remove from parental protection'), boundFunction(self.removeParentalProtection, current)), level=0)
                        if self.parentalControl.blacklist and config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached and config.ParentalControl.storeservicepin.value != "never":
                            append_when_current_valid(current, menu, (_("Unhide parental control services"), self.unhideParentalServices), level=0, key="1")
                    if SystemInfo['3DMode'] and fileExists('/usr/lib/enigma2/python/Plugins/SystemPlugins/OSD3DSetup/plugin.py'):
                        if eDVBDB.getInstance().getFlag(eServiceReference(current.toString())) & FLAG_IS_DEDICATED_3D:
                            append_when_current_valid(current, menu, (_('Unmark service as dedicated 3D service'), self.removeDedicated3DFlag), level=0)
                        else:
                            append_when_current_valid(current, menu, (_('Mark service as dedicated 3D service'), self.addDedicated3DFlag), level=0)
                    if not (current_sel_path):
                        if eDVBDB.getInstance().getFlag(eServiceReference(current.toString())) & FLAG_HIDE_VBI:
                            append_when_current_valid(current, menu, (_("Uncover dashed flickering line for this service"), self.removeHideVBIFlag), level=0)
                        else:
                            append_when_current_valid(current, menu, (_("Cover dashed flickering line for this service"), self.addHideVBIFlag), level=0)
                        if eDVBDB.getInstance().getCachedPid(eServiceReference(current.toString()), 9) >> 16 not in (-1, eDVBDB.getInstance().getCachedPid(eServiceReference(current.toString()), 2)):
                                 #Only show when a DVB subtitle is cached on this service
                                 if eDVBDB.getInstance().getFlag(eServiceReference(current.toString())) & FLAG_CENTER_DVB_SUBS:
                                          append_when_current_valid(current, menu, (_("Do not center DVB subs on this service"), self.removeCenterDVBSubsFlag), level=2)
                                 else:
                                          append_when_current_valid(current, menu, (_("Do center DVB subs on this service"), self.addCenterDVBSubsFlag), level=2)

                    if haveBouquets:
                        bouquets = self.csel.getBouquetList()
                        if bouquets is None:
                            bouquetCnt = 0
                        else:
                            bouquetCnt = len(bouquets)
                        if not self.inBouquet or bouquetCnt > 1:
                            append_when_current_valid(current, menu, (_('add service to bouquet'), self.addServiceToBouquetSelected), level=0, key='5')
                            self.addFunction = self.addServiceToBouquetSelected
                        if not self.inBouquet:
                            append_when_current_valid(current, menu, (_('remove entry'), self.removeEntry), level=0, key='8')
                            self.removeFunction = self.removeSatelliteService
                    elif not self.inBouquet:
                        append_when_current_valid(current, menu, (_('add service to favourites'), self.addServiceToBouquetSelected), level=0, key='5')
                        self.addFunction = self.addServiceToBouquetSelected
                    if SystemInfo["PIPAvailable"]:
                        self.PiPAvailable = True
            if self.csel.dopipzap:
                append_when_current_valid(current, menu, (_("play in mainwindow"), self.playMain), level=0, key="red")
            else:
                append_when_current_valid(current, menu, (_("play as picture in picture"), self.showServiceInPiP), level=0, key="blue")
            append_when_current_valid(current, menu, (_('find currently played service'), self.findCurrentlyPlayed), level=0, key='3')
        else:
                    if 'FROM SATELLITES' in current_root.getPath() and current and _('Services') in eServiceCenter.getInstance().info(current).getName(current):
                        unsigned_orbpos = current.getUnsignedData(4) >> 16
                        if unsigned_orbpos == 65535:
                            append_when_current_valid(current, menu, (_('remove cable services'), self.removeSatelliteServices), level=0)
                        elif unsigned_orbpos == 61166:
                            append_when_current_valid(current, menu, (_('remove terrestrial services'), self.removeSatelliteServices), level=0)
                        else:
                            append_when_current_valid(current, menu, (_('remove selected satellite'), self.removeSatelliteServices), level=0)
                    if haveBouquets:
                        if not self.inBouquet and 'PROVIDERS' not in current_sel_path:
                            append_when_current_valid(current, menu, (_('copy to bouquets'), self.copyCurrentToBouquetList), level=0)
                    if 'flags == %d' % FLAG_SERVICE_NEW_FOUND in current_sel_path:
                        append_when_current_valid(current, menu, (_('remove all new found flags'), self.removeAllNewFoundFlags), level=0)
        if self.inBouquet:
                    append_when_current_valid(current, menu, (_('rename entry'), self.renameEntry), level=0, key='2')
                    if not inAlternativeList:
                        append_when_current_valid(current, menu, (_('remove entry'), self.removeEntry), level=0, key='8')
                        self.removeFunction = self.removeCurrentService
        if current_root and 'flags == %d' % FLAG_SERVICE_NEW_FOUND in current_root.getPath():
                    append_when_current_valid(current, menu, (_('remove new found flag'), self.removeNewFoundFlag), level=0)
        else:
                if self.parentalControlEnabled:
                    if self.parentalControl.getProtectionLevel(current.toCompareString()) == -1:
                        append_when_current_valid(current, menu, (_('add bouquet to parental protection'), boundFunction(self.addParentalProtection, current)), level=0)
                    else:
                        append_when_current_valid(current, menu, (_('remove bouquet from parental protection'), boundFunction(self.removeParentalProtection, current)), level=0)
                menu.append(ChoiceEntryComponent(text=(_('add bouquet'), self.showBouquetInputBox)))
                append_when_current_valid(current, menu, (_('rename entry'), self.renameEntry), level=0, key='2')
                append_when_current_valid(current, menu, (_('remove entry'), self.removeEntry), level=0, key='8')
                self.removeFunction = self.removeBouquet
                if removed_userbouquets_available():
                    append_when_current_valid(current, menu, (_('purge deleted userbouquets'), self.purgeDeletedBouquets), level=0)
                    append_when_current_valid(current, menu, (_('restore deleted userbouquets'), self.restoreDeletedBouquets), level=0)
        if self.inBouquet:
            if csel.bouquet_mark_edit == OFF:
                if csel.movemode:
                    append_when_current_valid(current, menu, (_('disable move mode'), self.toggleMoveMode), level=0, key='6')
                else:
                    append_when_current_valid(current, menu, (_('enable move mode'), self.toggleMoveMode), level=1, key='6')
                if not csel.entry_marked and not inBouquetRootList and current_root and not current_root.flags & eServiceReference.isGroup:
                    if current.type != -1:
                        menu.append(ChoiceEntryComponent(text=(_('add marker'), self.showMarkerInputBox)))
                    if not csel.movemode:
                        if haveBouquets:
                            append_when_current_valid(current, menu, (_('enable bouquet edit'), self.bouquetMarkStart), level=0)
                        else:
                            append_when_current_valid(current, menu, (_('enable favourite edit'), self.bouquetMarkStart), level=0)
                    if current_sel_flags & eServiceReference.isGroup:
                        append_when_current_valid(current, menu, (_('edit alternatives'), self.editAlternativeServices), level=2)
                        append_when_current_valid(current, menu, (_('show alternatives'), self.showAlternativeServices), level=2)
                        append_when_current_valid(current, menu, (_('remove all alternatives'), self.removeAlternativeServices), level=2)
                    elif not current_sel_flags & eServiceReference.isMarker:
                        append_when_current_valid(current, menu, (_('add alternatives'), self.addAlternativeServices), level=2)
            elif csel.bouquet_mark_edit == EDIT_BOUQUET:
                if haveBouquets:
                    append_when_current_valid(current, menu, (_('end bouquet edit'), self.bouquetMarkEnd), level=0)
                    append_when_current_valid(current, menu, (_('abort bouquet edit'), self.bouquetMarkAbort), level=0)
                else:
                    append_when_current_valid(current, menu, (_('end favourites edit'), self.bouquetMarkEnd), level=0)
                    append_when_current_valid(current, menu, (_('abort favourites edit'), self.bouquetMarkAbort), level=0)
                if current_sel_flags & eServiceReference.isMarker:
                    append_when_current_valid(current, menu, (_('rename entry'), self.renameEntry), level=0, key='2')
                    append_when_current_valid(current, menu, (_('remove entry'), self.removeEntry), level=0, key='8')
                    self.removeFunction = self.removeCurrentService
            else:
                append_when_current_valid(current, menu, (_('end alternatives edit'), self.bouquetMarkEnd), level=0)
                append_when_current_valid(current, menu, (_('abort alternatives edit'), self.bouquetMarkAbort), level=0)
        menu.append(ChoiceEntryComponent('menu', (_('Configuration...'), self.openSetup)))
        self['menu'] = ChoiceList(menu)

    def set3DMode(self, value):
        playingref = self.session.nav.getCurrentlyPlayingServiceReference()
        if config.plugins.OSD3DSetup.mode.value == 'auto' and playingref and playingref == self.csel.getCurrentSelection():
            from Plugins.SystemPlugins.OSD3DSetup.plugin import applySettings
            applySettings(value and 'sidebyside' or config.plugins.OSD3DSetup.mode.value)

    def addDedicated3DFlag(self):
        eDVBDB.getInstance().addFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_IS_DEDICATED_3D)
        eDVBDB.getInstance().reloadBouquets()
        self.set3DMode(True)
        self.close()

    def removeDedicated3DFlag(self):
        eDVBDB.getInstance().removeFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_IS_DEDICATED_3D)
        eDVBDB.getInstance().reloadBouquets()
        self.set3DMode(False)
        self.close()

    def addHideVBIFlag(self):
        eDVBDB.getInstance().addFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_HIDE_VBI)
        eDVBDB.getInstance().reloadBouquets()
        Screens.InfoBar.InfoBar.instance.showHideVBI()
        self.close()

    def removeHideVBIFlag(self):
        eDVBDB.getInstance().removeFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_HIDE_VBI)
        eDVBDB.getInstance().reloadBouquets()
        Screens.InfoBar.InfoBar.instance.showHideVBI()
        self.close()

    def addCenterDVBSubsFlag(self):
        eDVBDB.getInstance().addFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_CENTER_DVB_SUBS)
        eDVBDB.getInstance().reloadBouquets()
        config.subtitles.dvb_subtitles_centered.value = True
        self.close()

    def removeCenterDVBSubsFlag(self):
        eDVBDB.getInstance().removeFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_CENTER_DVB_SUBS)
        eDVBDB.getInstance().reloadBouquets()
        config.subtitles.dvb_subtitles_centered.value = False
        self.close()

    def isProtected(self):
        return self.csel.protectContextMenu and config.ParentalControl.setuppinactive.value and config.ParentalControl.config_sections.context_menus.value

    def protectResult(self, answer):
        if answer:
            self.csel.protectContextMenu = False
        elif answer is not None:
            self.session.openWithCallback(self.close, MessageBox, _('The pin code you entered is wrong.'), MessageBox.TYPE_ERROR)
        else:
            self.close()

    def addServiceToBouquetOrAlternative(self):
        if self.addFunction:
            self.addFunction()
        else:
            return 0

    def getCurrentSelectionName(self):
        cur = self.csel.getCurrentSelection()
        if cur and cur.valid():
            name = eServiceCenter.getInstance().info(cur).getName(cur) or ServiceReference(cur).getServiceName() or ''
            name = name.replace('\xc2\x86', '').replace('\xc2\x87', '')
            return name
        return ''

    def removeEntry(self):
        if self.removeFunction and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid():
            if self.csel.confirmRemove:
                list = [(_('yes'), True), (_('no'), False), (_('yes') + ' ' + _('and never ask again this session again'), 'never')]
                self.session.openWithCallback(self.removeFunction, MessageBox, _('Are you sure to remove this entry?') + '\n%s' % self.getCurrentSelectionName(), list=list)
            else:
                self.removeFunction(True)
        else:
            return 0

    def removeCurrentService(self, answer):
        if answer:
            if answer == 'never':
                self.csel.confirmRemove = False
            self.csel.removeCurrentService()
            self.close()

    def removeSatelliteService(self, answer):
        if answer:
            if answer == 'never':
                self.csel.confirmRemove = False
            self.csel.removeSatelliteService()
            self.close()

    def removeBouquet(self, answer):
        if answer:
            self.csel.removeBouquet()
            eDVBDB.getInstance().reloadBouquets()
            self.close()

    def purgeDeletedBouquets(self):
        self.session.openWithCallback(self.purgeDeletedBouquetsCallback, MessageBox, _('Are you sure to purge all deleted userbouquets?'))

    def purgeDeletedBouquetsCallback(self, answer):
        if answer:
            for file in os.listdir('/etc/enigma2/'):
                if file.startswith('userbouquet') and file.endswith('.del'):
                    file = '/etc/enigma2/' + file
                    print 'permantly remove file ', file
                    os.remove(file)

            self.close()

    def restoreDeletedBouquets(self):
        for file in os.listdir('/etc/enigma2/'):
            if file.startswith('userbouquet') and file.endswith('.del'):
                file = '/etc/enigma2/' + file
                print 'restore file ', file[:-4]
                os.rename(file, file[:-4])

        eDVBDBInstance = eDVBDB.getInstance()
        eDVBDBInstance.setLoadUnlinkedUserbouquets(True)
        eDVBDBInstance.reloadBouquets()
        eDVBDBInstance.setLoadUnlinkedUserbouquets(config.misc.load_unlinked_userbouquets.value)
        refreshServiceList()
        self.csel.showFavourites()
        self.close()

    def playMain(self):
        ref = self.csel.getCurrentSelection()
        if ref and ref.valid() and self.PiPAvailable and self.csel.dopipzap:
            self.csel.zap()
            self.csel.startServiceRef = None
            self.csel.startRoot = None
            self.csel.correctChannelNumber()
            self.close(True)
        else:
            return 0

    def okbuttonClick(self):
        self['menu'].getCurrent()[0][1]()

    def openSetup(self):
        from Screens.Setup import Setup
        self.session.openWithCallback(self.cancelClick, Setup, 'userinterface')

    def cancelClick(self, dummy = False):
        self.close(False)

    def showServiceInformations(self):
        current = self.csel.getCurrentSelection()
        if current.flags & eServiceReference.isGroup:
            playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
            if playingref and playingref == current:
                current = self.session.nav.getCurrentlyPlayingServiceReference()
            else:
                current = eServiceReference(GetWithAlternative(current.toString()))
        self.session.open(ServiceInfo, current)
        self.close()

    def setStartupService(self):
        self.session.openWithCallback(self.setStartupServiceCallback, MessageBox, _('Set startup service'), list=[(_('Only on startup'), 'startup'), (_('Also on standby'), 'standby')])

    def setStartupServiceCallback(self, answer):
        if answer:
            config.servicelist.startupservice.value = self.csel.getCurrentSelection().toString()
            path = ';'.join([ i.toString() for i in self.csel.servicePath ])
            config.servicelist.startuproot.value = path
            config.servicelist.startupmode.value = config.servicelist.lastmode.value
            config.servicelist.startupservice_onstandby.value = answer == 'standby'
            config.servicelist.save()
            configfile.save()
            self.close()

    def unsetStartupService(self):
        config.servicelist.startupservice.value = ''
        config.servicelist.startupservice_onstandby.value = False
        config.servicelist.save()
        configfile.save()
        self.close()

    def showBouquetInputBox(self):
        self.session.openWithCallback(self.bouquetInputCallback, VirtualKeyBoard, title=_('Please enter a name for the new bouquet'), text='bouquetname', maxSize=False, visible_width=56, type=Input.TEXT)

    def bouquetInputCallback(self, bouquet):
        if bouquet is not None:
            self.csel.addBouquet(bouquet, None)
        self.close()

    def addParentalProtection(self, service):
        self.parentalControl.protectService(service.toCompareString())
        if config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached:
            self.csel.servicelist.resetRoot()
        self.close()

    def removeParentalProtection(self, service):
        self.session.openWithCallback(boundFunction(self.pinEntered, service.toCompareString()), PinInput, pinList=[config.ParentalControl.servicepin[0].value], triesEntry=config.ParentalControl.retries.servicepin, title=_('Enter the service pin'), windowTitle=_('Enter pin code'))

    def pinEntered(self, service, answer):
        if answer:
            self.parentalControl.unProtectService(service)
            if config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached:
                self.csel.servicelist.resetRoot()
            self.close()
        elif answer is not None:
            self.session.openWithCallback(self.close, MessageBox, _("The pin code you entered is wrong."), MessageBox.TYPE_ERROR)
        else:
            self.close()

    def unhideParentalServices(self):
        if self.csel.protectContextMenu:
            self.session.openWithCallback(self.unhideParentalServicesCallback, PinInput, pinList=[config.ParentalControl.servicepin[0].value], triesEntry=config.ParentalControl.retries.servicepin, title=_('Enter the service pin'), windowTitle=_('Enter pin code'))
        else:
            self.unhideParentalServicesCallback(True)

    def unhideParentalServicesCallback(self, answer):
        if answer:
            service = self.csel.servicelist.getCurrent()
            self.parentalControl.setSessionPinCached()
            self.parentalControl.hideBlacklist()
            self.csel.servicelist.resetRoot()
            self.csel.servicelist.setCurrent(service)
            self.close()
        elif answer is not None:
            self.session.openWithCallback(self.close, MessageBox, _('The pin code you entered is wrong.'), MessageBox.TYPE_ERROR)
        else:
            self.close()

    def showServiceInPiP(self, root=None, ref=None):
        newservice = ref or self.csel.getCurrentSelection()
        currentBouquet = root or self.csel.getRoot()
        if ref and root or (self.PiPAvailable and not self.csel.dopipzap and newservice and newservice.valid() and Components.ParentalControl.parentalControl.isServicePlayable(newservice, boundFunction(self.showServiceInPiP, root=currentBouquet), self.session)):
            if hasattr(self.session, 'pipshown') and self.session.pipshown and hasattr(self.session, 'pip'):
                del self.session.pip
            self.session.pip = self.session.instantiateDialog(PictureInPicture)
            self.session.pip.show()
            if self.session.pip.playService(newservice):
                self.session.pipshown = True
                self.session.pip.servicePath = self.csel.getCurrentServicePath()
                self.session.pip.servicePath[1] = currentBouquet
                self.close(True)
            else:
                self.session.pipshown = False
                del self.session.pip
                self.session.openWithCallback(self.close, MessageBox, _("Could not open Picture in Picture"), MessageBox.TYPE_ERROR)
        else:
            return 0

    def addServiceToBouquetSelected(self):
        bouquets = self.csel.getBouquetList()
        if bouquets is None:
            cnt = 0
        else:
            cnt = len(bouquets)
        if cnt > 1:
            self.bsel = self.session.openWithCallback(self.bouquetSelClosed, BouquetSelector, bouquets, self.addCurrentServiceToBouquet)
        elif cnt == 1:
            self.addCurrentServiceToBouquet(bouquets[0][1], closeBouquetSelection=False)

    def bouquetSelClosed(self, recursive):
        self.bsel = None
        if recursive:
            self.close(False)

    def removeSatelliteServices(self):
        self.csel.removeSatelliteServices()
        self.close()

    def copyCurrentToBouquetList(self):
        self.csel.copyCurrentToBouquetList()
        self.close()

    def showMarkerInputBox(self):
        self.session.openWithCallback(self.markerInputCallback, VirtualKeyBoard, title=_('Please enter a name for the new marker'), text='markername', maxSize=False, visible_width=56, type=Input.TEXT)

    def markerInputCallback(self, marker):
        if marker is not None:
            self.csel.addMarker(marker)
        self.close()

    def addCurrentServiceToBouquet(self, dest, closeBouquetSelection = True):
        self.csel.addServiceToBouquet(dest)
        if self.bsel is not None:
            self.bsel.close(True)
        else:
            self.close(closeBouquetSelection)

    def renameEntry(self):
        if self.inBouquet and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid() and not self.csel.entry_marked:
            self.csel.renameEntry()
            self.close()
        else:
            return 0

    def toggleMoveMode(self):
        if self.inBouquet and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid():
            self.csel.toggleMoveMode()
            self.close()
        else:
            return 0

    def toggleMoveModeSelect(self):
        if self.inBouquet and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid():
            self.csel.toggleMoveMode(True)
            self.close()
        else:
            return 0

    def bouquetMarkStart(self):
        self.csel.startMarkedEdit(EDIT_BOUQUET)
        self.close()

    def bouquetMarkEnd(self):
        self.csel.endMarkedEdit(abort=False)
        self.close()

    def bouquetMarkAbort(self):
        self.csel.endMarkedEdit(abort=True)
        self.close()

    def removeNewFoundFlag(self):
        eDVBDB.getInstance().removeFlag(self.csel.getCurrentSelection(), FLAG_SERVICE_NEW_FOUND)
        self.close()

    def removeAllNewFoundFlags(self):
        curpath = self.csel.getCurrentSelection().getPath()
        idx = curpath.find('satellitePosition == ')
        if idx != -1:
            tmp = curpath[idx + 21:]
            idx = tmp.find(')')
            if idx != -1:
                satpos = int(tmp[:idx])
                eDVBDB.getInstance().removeFlags(FLAG_SERVICE_NEW_FOUND, -1, -1, -1, satpos)
        self.close()

    def editAlternativeServices(self):
        self.csel.startMarkedEdit(EDIT_ALTERNATIVES)
        self.close()

    def showAlternativeServices(self):
        self.csel['Service'].editmode = True
        self.csel.enterPath(self.csel.getCurrentSelection())
        self.close()

    def removeAlternativeServices(self):
        self.csel.removeAlternativeServices()
        self.close()

    def addAlternativeServices(self):
        self.csel.addAlternativeServices()
        self.csel.startMarkedEdit(EDIT_ALTERNATIVES)
        self.close()

    def findCurrentlyPlayed(self):
        sel = self.csel.getCurrentSelection()
        if sel and sel.valid() and not self.csel.entry_marked:
            currentPlayingService = hasattr(self.csel, 'dopipzap') and self.csel.dopipzap and self.session.pip.getCurrentService() or self.session.nav.getCurrentlyPlayingServiceOrGroup()
            self.csel.servicelist.setCurrent(currentPlayingService, adjust=False)
            if self.csel.getCurrentSelection() != currentPlayingService:
                self.csel.setCurrentSelection(sel)
            self.close()
        else:
            return 0

    def runPlugin(self, plugin):
        plugin(session=self.session, service=self.csel.getCurrentSelection())
        self.close()


class SelectionEventInfo():

    def __init__(self):
        self['Service'] = self['ServiceEvent'] = ServiceEvent()
        self['Event'] = Event()
        self.servicelist.connectSelChanged(self.__selectionChanged)
        self.timer = eTimer()
        self.timer.callback.append(self.updateEventInfo)
        self.onShown.append(self.__selectionChanged)

    def __selectionChanged(self):
        if self.execing:
            self.timer.start(100, True)

    def updateEventInfo(self):
        cur = self.getCurrentSelection()
        service = self['Service']
        service.newService(cur)
        self['Event'].newEvent(service.event)


class ChannelSelectionEPG(InfoBarHotkey):

    def __init__(self):
        self.hotkeys = [('Info (EPG)', 'info', 'Infobar/openEventView'),
         ('Info (EPG) ' + _('long'), 'info_long', 'Infobar/showEventInfoPlugins'),
         ('Epg/Guide', 'epg', 'Plugins/Extensions/GraphMultiEPG/1'),
         ('Epg/Guide ' + _('long'), 'epg_long', 'Infobar/showEventInfoPlugins')]
        self['ChannelSelectEPGActions'] = hotkeyActionMap(['ChannelSelectEPGActions'], dict(((x[1], self.hotkeyGlobal) for x in self.hotkeys)))
        self.eventViewEPG = self.start_bouquet = self.epg_bouquet = None
        self.currentSavedPath = []

    def getKeyFunctions(self, key):
        selection = eval('config.misc.hotkey.' + key + ".value.split(',')")
        selected = []
        for x in selection:
            function = list((function for function in getHotkeyFunctions() if function[1] == x and function[2] == 'EPG'))
            if function:
                selected.append(function[0])

        return selected

    def runPlugin(self, plugin):
        Screens.InfoBar.InfoBar.instance.runPlugin(plugin)

    def getEPGPluginList(self, getAll = False):
        pluginlist = [ (p.name, boundFunction(self.runPlugin, p), p.path) for p in plugins.getPlugins(where=PluginDescriptor.WHERE_EVENTINFO) if 'selectedevent' not in p.__call__.func_code.co_varnames ] or []
        from Components.ServiceEventTracker import InfoBarCount
        if getAll or InfoBarCount == 1:
            pluginlist.append((_('Show EPG for current channel...'), self.openSingleServiceEPG, 'current_channel'))
        pluginlist.append((_('Multi EPG'), self.openMultiServiceEPG, 'multi_epg'))
        pluginlist.append((_('Current event EPG'), self.openEventView, 'event_epg'))
        return pluginlist

    def showEventInfoPlugins(self):
        pluginlist = self.getEPGPluginList()
        if pluginlist:
            self.session.openWithCallback(self.EventInfoPluginChosen, ChoiceBox, title=_('Please choose an extension...'), list=pluginlist, skin_name='EPGExtensionsList')
        else:
            self.openSingleServiceEPG()

    def EventInfoPluginChosen(self, answer):
        if answer is not None:
            answer[1]()

    def openEventView(self):
        epglist = []
        self.epglist = epglist
        ref = self.getCurrentSelection()
        epg = eEPGCache.getInstance()
        now_event = epg.lookupEventTime(ref, -1, 0)
        if now_event:
            epglist.append(now_event)
            next_event = epg.lookupEventTime(ref, -1, 1)
            if next_event:
                epglist.append(next_event)
        if epglist:
            self.eventViewEPG = self.session.openWithCallback(self.eventViewEPGClosed, EventViewEPGSelect, epglist[0], ServiceReference(ref), self.eventViewEPGCallback, self.openSingleServiceEPG, self.openMultiServiceEPG, self.openSimilarList)

    def eventViewEPGCallback(self, setEvent, setService, val):
        epglist = self.epglist
        if len(epglist) > 1:
            tmp = epglist[0]
            epglist[0] = epglist[1]
            epglist[1] = tmp
            setEvent(epglist[0])

    def eventViewEPGClosed(self, ret = False):
        self.eventViewEPG = None
        if ret:
            self.close()

    def openMultiServiceEPG(self):
        ref = self.getCurrentSelection()
        if ref:
            self.start_bouquet = self.epg_bouquet = self.servicelist.getRoot()
            self.savedService = ref
            self.currentSavedPath = self.servicePath[:]
            services = self.getServicesList(self.servicelist.getRoot())
            self.session.openWithCallback(self.SingleMultiEPGClosed, EPGSelection, services, self.zapToService, None, bouquetChangeCB=self.changeBouquetForMultiEPG)

    def openSingleServiceEPG(self):
        ref = self.getCurrentSelection()
        if ref:
            self.start_bouquet = self.epg_bouquet = self.servicelist.getRoot()
            self.savedService = ref
            self.currentSavedPath = self.servicePath[:]
            self.session.openWithCallback(self.SingleMultiEPGClosed, EPGSelection, ref, self.zapToService, serviceChangeCB=self.changeServiceCB, bouquetChangeCB=self.changeBouquetForSingleEPG)

    def openSimilarList(self, eventid, refstr):
        self.session.open(EPGSelection, refstr, None, eventid)

    def getServicesList(self, root):
        services = []
        servicelist = root and eServiceCenter.getInstance().list(root)
        if servicelist is not None:
            while True:
                service = servicelist.getNext()
                if not service.valid():
                    break
                if service.flags & (eServiceReference.isDirectory | eServiceReference.isMarker):
                    continue
                services.append(ServiceReference(service))

        return services

    def SingleMultiEPGClosed(self, ret = False):
        if ret:
            service = self.getCurrentSelection()
            if self.eventViewEPG:
                self.eventViewEPG.close(service)
            elif service is not None:
                self.close()
        else:
            if self.start_bouquet != self.epg_bouquet and len(self.currentSavedPath) > 0:
                self.clearPath()
                self.enterPath(self.bouquet_root)
                self.epg_bouquet = self.start_bouquet
                self.enterPath(self.epg_bouquet)
            self.setCurrentSelection(self.savedService)

    def changeBouquetForSingleEPG(self, direction, epg):
        if config.usage.multibouquet.value:
            inBouquet = self.getMutableList() is not None
            if inBouquet and len(self.servicePath) > 1:
                self.pathUp()
                if direction < 0:
                    self.moveUp()
                else:
                    self.moveDown()
                cur = self.getCurrentSelection()
                self.enterPath(cur)
                self.epg_bouquet = self.servicelist.getRoot()
                epg.setService(ServiceReference(self.getCurrentSelection()))

    def changeBouquetForMultiEPG(self, direction, epg):
        if config.usage.multibouquet.value:
            inBouquet = self.getMutableList() is not None
            if inBouquet and len(self.servicePath) > 1:
                self.pathUp()
                if direction < 0:
                    self.moveUp()
                else:
                    self.moveDown()
                cur = self.getCurrentSelection()
                self.enterPath(cur)
                self.epg_bouquet = self.servicelist.getRoot()
                services = self.getServicesList(self.epg_bouquet)
                epg.setServices(services)

    def changeServiceCB(self, direction, epg):
        beg = self.getCurrentSelection()
        while True:
            if direction > 0:
                self.moveDown()
            else:
                self.moveUp()
            cur = self.getCurrentSelection()
            if cur == beg or not cur.flags & eServiceReference.isMarker:
                break

        epg.setService(ServiceReference(self.getCurrentSelection()))

    def zapToService(self, service, preview = False, zapback = False):
        if self.startServiceRef is None:
            self.startServiceRef = self.session.nav.getCurrentlyPlayingServiceOrGroup()
        if service is not None:
            if self.servicelist.getRoot() != self.epg_bouquet:
                self.servicelist.clearPath()
                if self.servicelist.bouquet_root != self.epg_bouquet:
                    self.servicelist.enterPath(self.servicelist.bouquet_root)
                self.servicelist.enterPath(self.epg_bouquet)
            self.servicelist.setCurrent(service)
        if not zapback or preview:
            self.zap(enable_pipzap=True)
        if (self.dopipzap or zapback) and not preview:
            self.zapBack()
        if not preview:
            self.startServiceRef = None
            self.startRoot = None
            self.revertMode = None


class ChannelSelectionEdit():

    def __init__(self):
        self.entry_marked = False
        self.bouquet_mark_edit = OFF
        self.mutableList = None
        self.__marked = []
        self.saved_title = None
        self.saved_root = None
        self.current_ref = None
        self.editMode = False
        self.confirmRemove = True

        class ChannelSelectionEditActionMap(ActionMap):

            def __init__(self, csel, contexts = [], actions = {}, prio = 0):
                ActionMap.__init__(self, contexts, actions, prio)
                self.csel = csel

            def action(self, contexts, action):
                if action == 'cancel':
                    self.csel.handleEditCancel()
                    return 0
                elif action == 'ok':
                    return 0
                else:
                    return ActionMap.action(self, contexts, action)

        self['ChannelSelectEditActions'] = ChannelSelectionEditActionMap(self, ['ChannelSelectEditActions', 'OkCancelActions'], {'contextMenu': self.doContext})

    def getMutableList(self, root = eServiceReference()):
        if self.mutableList is not None:
            return self.mutableList
        serviceHandler = eServiceCenter.getInstance()
        if not root.valid():
            root = self.getRoot()
        list = root and serviceHandler.list(root)
        if list is not None:
            return list.startEdit()

    def buildBouquetID(self, name):
        name = unicodedata.normalize('NFKD', unicode(name, 'utf_8', errors='ignore')).encode('ASCII', 'ignore').translate(None, '<>:"/\\|?*() ')
        while os.path.isfile((self.mode == MODE_TV and '/etc/enigma2/userbouquet.%s.tv' or '/etc/enigma2/userbouquet.%s.radio') % name):
            name = name.rsplit('_', 1)
            name = '_'.join((name[0], len(name) == 2 and name[1].isdigit() and str(int(name[1]) + 1) or '1'))

        return name

    def renameEntry(self):
        self.editMode = True
        cur = self.getCurrentSelection()
        if cur and cur.valid():
            name = eServiceCenter.getInstance().info(cur).getName(cur) or ServiceReference(cur).getServiceName() or ''
            name = name.replace('\xc2\x86', '').replace('\xc2\x87', '')
            if name:
                self.session.openWithCallback(self.renameEntryCallback, VirtualKeyBoard, title=_('Please enter new name:'), text=name)
        else:
            return 0

    def renameEntryCallback(self, name):
        if name:
            mutableList = self.getMutableList()
            if mutableList:
                current = self.servicelist.getCurrent()
                current.setName(name)
                index = self.servicelist.getCurrentIndex()
                mutableList.removeService(current, False)
                mutableList.addService(current)
                mutableList.moveService(current, index)
                mutableList.flushChanges()
                self.servicelist.addService(current, True)
                self.servicelist.removeCurrent()
                if not self.servicelist.atEnd():
                    self.servicelist.moveUp()

    def addMarker(self, name):
        current = self.servicelist.getCurrent()
        mutableList = self.getMutableList()
        cnt = 0
        while mutableList:
            str = '1:64:%d:0:0:0:0:0:0:0::%s' % (cnt, name)
            ref = eServiceReference(str)
            if current and current.valid():
                if not mutableList.addService(ref, current):
                    self.servicelist.addService(ref, True)
                    mutableList.flushChanges()
                    break
            elif not mutableList.addService(ref):
                self.servicelist.addService(ref, True)
                mutableList.flushChanges()
                break
            cnt += 1

    def addAlternativeServices(self):
        cur_service = ServiceReference(self.getCurrentSelection())
        end = self.atEnd()
        root = self.getRoot()
        cur_root = root and ServiceReference(root)
        mutableBouquet = cur_root.list().startEdit()
        if mutableBouquet:
            name = cur_service.getServiceName()
            refstr = '_'.join(cur_service.ref.toString().split(':'))
            if self.mode == MODE_TV:
                str = '1:134:1:0:0:0:0:0:0:0:FROM BOUQUET "alternatives.%s.tv" ORDER BY bouquet' % refstr
            else:
                str = '1:134:2:0:0:0:0:0:0:0:FROM BOUQUET "alternatives.%s.radio" ORDER BY bouquet' % refstr
            new_ref = ServiceReference(str)
            if not mutableBouquet.addService(new_ref.ref, cur_service.ref):
                mutableBouquet.removeService(cur_service.ref)
                mutableBouquet.flushChanges()
                eDVBDB.getInstance().reloadBouquets()
                mutableAlternatives = new_ref.list().startEdit()
                if mutableAlternatives:
                    mutableAlternatives.setListName(name)
                    if mutableAlternatives.addService(cur_service.ref):
                        print 'add', cur_service.ref.toString(), 'to new alternatives failed'
                    mutableAlternatives.flushChanges()
                    self.servicelist.addService(new_ref.ref, True)
                    self.servicelist.removeCurrent()
                    if not end:
                        self.servicelist.moveUp()
                    if cur_service.ref.toString() == self.lastservice.value:
                        self.saveChannel(new_ref.ref)
                    if self.startServiceRef and cur_service.ref == self.startServiceRef:
                        self.startServiceRef = new_ref.ref
                else:
                    print 'get mutable list for new created alternatives failed'
            else:
                print 'add', str, 'to', cur_root.getServiceName(), 'failed'
        else:
            print 'bouquetlist is not editable'

    def addBouquet(self, bName, services):
        serviceHandler = eServiceCenter.getInstance()
        mutableBouquetList = serviceHandler.list(self.bouquet_root).startEdit()
        if mutableBouquetList:
            bName = self.buildBouquetID(bName)
            new_bouquet_ref = eServiceReference((self.mode == MODE_TV and '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.%s.tv" ORDER BY bouquet' or '1:7:2:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.%s.radio" ORDER BY bouquet') % bName)
            if not mutableBouquetList.addService(new_bouquet_ref):
                mutableBouquetList.flushChanges()
                eDVBDB.getInstance().reloadBouquets()
                mutableBouquet = serviceHandler.list(new_bouquet_ref).startEdit()
                if mutableBouquet:
                    mutableBouquet.setListName(bName)
                    if services is not None:
                        for service in services:
                            if mutableBouquet.addService(service):
                                print 'add', service.toString(), 'to new bouquet failed'

                    mutableBouquet.flushChanges()
                else:
                    print 'get mutable list for new created bouquet failed'
                cur_root = self.getRoot()
                str1 = cur_root and cur_root.toString()
                pos1 = str1 and str1.find('FROM BOUQUET') or -1
                pos2 = self.bouquet_rootstr.find('FROM BOUQUET')
                if pos1 != -1 and pos2 != -1 and str1[pos1:] == self.bouquet_rootstr[pos2:]:
                    self.servicelist.addService(new_bouquet_ref)
                    self.servicelist.resetRoot()
            else:
                print 'add', str, 'to bouquets failed'
        else:
            print 'bouquetlist is not editable'

    def copyCurrentToBouquetList(self):
        provider = ServiceReference(self.getCurrentSelection())
        providerName = provider.getServiceName()
        serviceHandler = eServiceCenter.getInstance()
        services = serviceHandler.list(provider.ref)
        self.addBouquet(providerName, services and services.getContent('R', True))

    def removeAlternativeServices(self):
        cur_service = ServiceReference(self.getCurrentSelection())
        end = self.atEnd()
        root = self.getRoot()
        cur_root = root and ServiceReference(root)
        list = cur_service.list()
        first_in_alternative = list and list.getNext()
        if first_in_alternative:
            edit_root = cur_root and cur_root.list().startEdit()
            if edit_root:
                if not edit_root.addService(first_in_alternative, cur_service.ref):
                    self.servicelist.addService(first_in_alternative, True)
                    if cur_service.ref.toString() == self.lastservice.value:
                        self.saveChannel(first_in_alternative)
                    if self.startServiceRef and cur_service.ref == self.startServiceRef:
                        self.startServiceRef = first_in_alternative
                else:
                    print "couldn't add first alternative service to current root"
            else:
                print "couldn't edit current root!!"
        else:
            print 'remove empty alternative list !!'
        self.removeBouquet()
        if not end:
            self.servicelist.moveUp()

    def removeBouquet(self):
        refstr = self.getCurrentSelection().toString()
        print 'removeBouquet', refstr
        pos = refstr.find('FROM BOUQUET "')
        filename = None
        self.removeCurrentService(bouquet=True)

    def removeSatelliteService(self):
        current = self.getCurrentSelection()
        eDVBDB.getInstance().removeService(current)
        refreshServiceList()
        if not self.atEnd():
            self.servicelist.moveUp()

    def removeSatelliteServices(self):
        current = self.getCurrentSelection()
        unsigned_orbpos = current.getUnsignedData(4) >> 16
        if unsigned_orbpos == 65535:
            messageText = _('Are you sure to remove all cable services?')
        elif unsigned_orbpos == 61166:
            messageText = _('Are you sure to remove all terrestrial services?')
        else:
            if unsigned_orbpos > 1800:
                unsigned_orbpos = 3600 - unsigned_orbpos
                direction = _('W')
            else:
                direction = _('E')
            messageText = _('Are you sure to remove all %d.%d%s%s services?') % (unsigned_orbpos / 10,
             unsigned_orbpos % 10,
             '\xc2\xb0',
             direction)
        self.session.openWithCallback(self.removeSatelliteServicesCallback, MessageBox, messageText)

    def removeSatelliteServicesCallback(self, answer):
        if answer:
            currentIndex = self.servicelist.getCurrentIndex()
            current = self.getCurrentSelection()
            unsigned_orbpos = current.getUnsignedData(4) >> 16
            if unsigned_orbpos == 65535:
                eDVBDB.getInstance().removeServices(int('0xFFFF0000', 16) - 4294967296L)
            elif unsigned_orbpos == 61166:
                eDVBDB.getInstance().removeServices(int('0xEEEE0000', 16) - 4294967296L)
            else:
                curpath = current.getPath()
                idx = curpath.find('satellitePosition == ')
                if idx != -1:
                    tmp = curpath[idx + 21:]
                    idx = tmp.find(')')
                    if idx != -1:
                        satpos = int(tmp[:idx])
                        eDVBDB.getInstance().removeServices(-1, -1, -1, satpos)
            refreshServiceList()
            if hasattr(self, 'showSatellites'):
                self.showSatellites()
                self.servicelist.moveToIndex(currentIndex)
                if currentIndex != self.servicelist.getCurrentIndex():
                    self.servicelist.instance.moveSelection(self.servicelist.instance.moveEnd)

    def startMarkedEdit(self, type):
        self.savedPath = self.servicePath[:]
        if type == EDIT_ALTERNATIVES:
            self.current_ref = self.getCurrentSelection()
            self.enterPath(self.current_ref)
        self.mutableList = self.getMutableList()
        self.clearMarks()
        self.saved_title = self.getTitle()
        pos = self.saved_title.find(')')
        new_title = self.saved_title[:pos + 1]
        if type == EDIT_ALTERNATIVES:
            self.bouquet_mark_edit = EDIT_ALTERNATIVES
            new_title += ' ' + _('[alternative edit]')
        else:
            self.bouquet_mark_edit = EDIT_BOUQUET
            if config.usage.multibouquet.value:
                new_title += ' ' + _('[bouquet edit]')
            else:
                new_title += ' ' + _('[favourite edit]')
        self.setTitle(new_title)
        self.__marked = self.servicelist.getRootServices()
        for x in self.__marked:
            self.servicelist.addMarked(eServiceReference(x))

        self['Service'].editmode = True

    def endMarkedEdit(self, abort):
        if not abort and self.mutableList is not None:
            new_marked = set(self.servicelist.getMarked())
            old_marked = set(self.__marked)
            removed = old_marked - new_marked
            added = new_marked - old_marked
            changed = False
            for x in removed:
                changed = True
                self.mutableList.removeService(eServiceReference(x))

            for x in added:
                changed = True
                self.mutableList.addService(eServiceReference(x))

            if changed:
                if self.bouquet_mark_edit == EDIT_ALTERNATIVES and not new_marked and self.__marked:
                    self.mutableList.addService(eServiceReference(self.__marked[0]))
                self.mutableList.flushChanges()
        self.__marked = []
        self.clearMarks()
        self.bouquet_mark_edit = OFF
        self.mutableList = None
        self.setTitle(self.saved_title)
        self.saved_title = None
        del self.servicePath[:]
        self.servicePath += self.savedPath
        del self.savedPath
        self.setRoot(self.servicePath[-1])
        if self.current_ref:
            self.setCurrentSelection(self.current_ref)
            self.current_ref = None

    def clearMarks(self):
        self.servicelist.clearMarks()

    def doMark(self):
        ref = self.servicelist.getCurrent()
        if self.servicelist.isMarked(ref):
            self.servicelist.removeMarked(ref)
        else:
            self.servicelist.addMarked(ref)

    def removeCurrentEntry(self, bouquet = False):
        if self.confirmRemove:
            list = [(_('yes'), True), (_('no'), False), (_('yes') + ' ' + _('and never ask again this session again'), 'never')]
            self.session.openWithCallback(boundFunction(self.removeCurrentEntryCallback, bouquet), MessageBox, _('Are you sure to remove this entry?'), list=list)
        else:
            self.removeCurrentEntryCallback(bouquet, True)

    def removeCurrentEntryCallback(self, bouquet, answer):
        if answer:
            if answer == 'never':
                self.confirmRemove = False
            if bouquet:
                self.removeBouquet()
            else:
                self.removeCurrentService()

    def removeCurrentService(self, bouquet = False):
        self.editMode = True
        ref = self.servicelist.getCurrent()
        mutableList = self.getMutableList()
        if ref.valid() and mutableList is not None:
            if not mutableList.removeService(ref):
                mutableList.flushChanges()
                self.servicelist.removeCurrent()
                self.servicelist.resetRoot()
                playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
                if not bouquet and playingref and ref == playingref:
                    self.channelSelected(doClose=False)

    def addServiceToBouquet(self, dest, service = None):
        mutableList = self.getMutableList(dest)
        if mutableList is not None:
            if service is None:
                service = self.servicelist.getCurrent()
            if not mutableList.addService(service):
                mutableList.flushChanges()
                cur_root = self.getRoot()
                str1 = cur_root and cur_root.toString() or -1
                str2 = dest.toString()
                pos1 = str1.find('FROM BOUQUET')
                pos2 = str2.find('FROM BOUQUET')
                if pos1 != -1 and pos2 != -1 and str1[pos1:] == str2[pos2:]:
                    self.servicelist.addService(service)
                self.servicelist.resetRoot()

    def toggleMoveMode(self, select = False):
        self.editMode = True
        if self.movemode:
            if self.entry_marked:
                self.toggleMoveMarked()
            self.movemode = False
            self.mutableList.flushChanges()
            self.mutableList = None
            self.setTitle(self.saved_title)
            self.saved_title = None
            self.servicelist.resetRoot()
            self.servicelist.l.setHideNumberMarker(config.usage.hide_number_markers.value)
            self.setCurrentSelection(self.servicelist.getCurrent())
        else:
            self.mutableList = self.getMutableList()
            self.movemode = True
            select and self.toggleMoveMarked()
            self.saved_title = self.getTitle()
            pos = self.saved_title.find(')')
            self.setTitle(self.saved_title[:pos + 1] + ' ' + _('[move mode]') + self.saved_title[pos + 1:])
            self.servicelist.l.setHideNumberMarker(False)
            self.setCurrentSelection(self.servicelist.getCurrent())
        self['Service'].editmode = True

    def handleEditCancel(self):
        if self.movemode:
            self.toggleMoveMode()
        elif self.bouquet_mark_edit != OFF:
            self.endMarkedEdit(True)

    def toggleMoveMarked(self):
        if self.entry_marked:
            self.servicelist.setCurrentMarked(False)
            self.entry_marked = False
            self.pathChangeDisabled = False
        else:
            self.servicelist.setCurrentMarked(True)
            self.entry_marked = True
            self.pathChangeDisabled = True

    def doContext(self):
        self.session.openWithCallback(self.exitContext, ChannelContextMenu, self)

    def exitContext(self, close = False):
        if close:
            self.cancel()


MODE_TV = 0
MODE_RADIO = 1
service_types_tv = '1:7:1:0:0:0:0:0:0:0:(type == 1) || (type == 17) || (type == 22) || (type == 25) || (type == 31) || (type == 134) || (type == 195)'
service_types_radio = '1:7:2:0:0:0:0:0:0:0:(type == 2) || (type == 10)'

class ChannelSelectionBase(Screen):

    def __init__(self, session):
        Screen.__init__(self, session)
        self.setScreenPathMode(None)
        self['key_red'] = Button(_('All'))
        self['key_green'] = Button(_('Satellites'))
        self['key_yellow'] = Button(_('Provider'))
        self['key_blue'] = Button(_('Favourites'))
        self['list'] = ServiceList(self)
        self.servicelist = self['list']
        self.numericalTextInput = NumericalTextInput(handleTimeout=False)
        self.numericalTextInput.setUseableChars(u'1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        self.servicePathTV = []
        self.servicePathRadio = []
        self.servicePath = []
        self.history = []
        self.rootChanged = False
        self.startRoot = None
        self.selectionNumber = ''
        self.clearNumberSelectionNumberTimer = eTimer()
        self.clearNumberSelectionNumberTimer.callback.append(self.clearNumberSelectionNumber)
        self.protectContextMenu = True
        self.mode = MODE_TV
        self.dopipzap = False
        self.pathChangeDisabled = False
        self.movemode = False
        self.showSatDetails = False
        self['ChannelSelectBaseActions'] = NumberActionMap(['ChannelSelectBaseActions', 'NumberActions', 'InputAsciiActions'], {'showFavourites': self.showFavourites,
         'showAllServices': self.showAllServices,
         'showProviders': self.showProviders,
         'showSatellites': boundFunction(self.showSatellites, changeMode=True),
         'nextBouquet': self.nextBouquet,
         'prevBouquet': self.prevBouquet,
         'nextMarker': self.nextMarker,
         'prevMarker': self.prevMarker,
         'gotAsciiCode': self.keyAsciiCode,
         'keyLeft': self.keyLeft,
         'keyRight': self.keyRight,
         'keyRecord': self.keyRecord,
         '1': self.keyNumberGlobal,
         '2': self.keyNumberGlobal,
         '3': self.keyNumberGlobal,
         '4': self.keyNumberGlobal,
         '5': self.keyNumberGlobal,
         '6': self.keyNumberGlobal,
         '7': self.keyNumberGlobal,
         '8': self.keyNumberGlobal,
         '9': self.keyNumberGlobal,
         '0': self.keyNumber0}, -2)
        self.maintitle = _('Channel selection')
        self.recallBouquetMode()

    def getBouquetNumOffset(self, bouquet):
        if not config.usage.multibouquet.value:
            return 0
        str = bouquet.toString()
        offset = 0
        if 'userbouquet.' in bouquet.toCompareString():
            serviceHandler = eServiceCenter.getInstance()
            servicelist = serviceHandler.list(bouquet)
            if servicelist is not None:
                while True:
                    serviceIterator = servicelist.getNext()
                    if not serviceIterator.valid():
                        break
                    number = serviceIterator.getChannelNum()
                    if number > 0:
                        offset = number - 1
                        break

        return offset

    def recallBouquetMode(self):
        if self.mode == MODE_TV:
            self.service_types = service_types_tv
            if config.usage.multibouquet.value:
                self.bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
            else:
                self.bouquet_rootstr = '%s FROM BOUQUET "userbouquet.favourites.tv" ORDER BY bouquet' % self.service_types
        else:
            self.service_types = service_types_radio
            if config.usage.multibouquet.value:
                self.bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.radio" ORDER BY bouquet'
            else:
                self.bouquet_rootstr = '%s FROM BOUQUET "userbouquet.favourites.radio" ORDER BY bouquet' % self.service_types
        self.bouquet_root = eServiceReference(self.bouquet_rootstr)

    def setTvMode(self):
        self.mode = MODE_TV
        self.servicePath = self.servicePathTV
        self.recallBouquetMode()
        title = self.maintitle
        pos = title.find(' (')
        if pos != -1:
            title = title[:pos]
        title += _(' (TV)')
        self.setTitle(title)

    def setRadioMode(self):
        self.mode = MODE_RADIO
        self.servicePath = self.servicePathRadio
        self.recallBouquetMode()
        title = self.maintitle
        pos = title.find(' (')
        if pos != -1:
            title = title[:pos]
