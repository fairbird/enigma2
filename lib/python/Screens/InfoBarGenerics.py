from ChannelSelection import ChannelSelection, BouquetSelector, SilentBouquetSelector
from Components.ActionMap import ActionMap, HelpableActionMap
from Components.ActionMap import NumberActionMap
from Components.Harddisk import harddiskmanager
from Components.Input import Input
from Components.Label import Label
from Components.MovieList import AUDIO_EXTENSIONS, MOVIE_EXTENSIONS, DVD_EXTENSIONS
from Components.PluginComponent import plugins
from Components.ServiceEventTracker import ServiceEventTracker
from Components.Sources.Boolean import Boolean
from Components.config import config, ConfigBoolean, ConfigClock, ConfigText
from Components.SystemInfo import SystemInfo
from Components.UsageConfig import preferredInstantRecordPath, defaultMoviePath, ConfigSelection
from Components.VolumeControl import VolumeControl
from Components.Sources.StaticText import StaticText
from EpgSelection import EPGSelection
from Plugins.Plugin import PluginDescriptor
from Screen import Screen
from Screens import ScreenSaver
from Screens import Standby
from Screens.ChoiceBox import ChoiceBox
from Screens.Dish import Dish
from Screens.EventView import EventViewEPGSelect, EventViewSimple
from Screens.InputBox import InputBox
from Screens.MessageBox import MessageBox
from Screens.MinuteInput import MinuteInput
from Screens.TimerSelection import TimerSelection
from Screens.PictureInPicture import PictureInPicture
import Screens.Standby
from Screens.SubtitleDisplay import SubtitleDisplay
from Screens.RdsDisplay import RdsInfoDisplay, RassInteractive
from Screens.TimeDateInput import TimeDateInput
from Screens.UnhandledKey import UnhandledKey
from ServiceReference import ServiceReference, isPlayableForCur
from Tools import Notifications, ASCIItranslit
from Tools.Directories import fileExists, getRecordingFilename, moveFiles
from enigma import eTimer, eServiceCenter, eDVBServicePMTHandler, iServiceInformation, iPlayableService, eServiceReference, eEPGCache, eActionMap, getBoxType, getDesktop, eDVBDB
from time import time, localtime, strftime
import os
from bisect import insort


from RecordTimer import RecordTimerEntry, RecordTimer, findSafeRecordPath

# hack alert!
from Menu import MainMenu, mdom

# sys.maxint on 64bit (2**63-1) fails with OverflowError on eActionMap.bindAction use 32bit value (2**31-1)
maxint = 2147483647

from Components.config import ConfigInteger
from os import stat as os_stat, remove as os_remove

def isStandardInfoBar(self):
    return self.__class__.__name__ == 'InfoBar'


def setResumePoint(session):
    global resumePointCacheLast
    global resumePointCache
    service = session.nav.getCurrentService()
    ref = session.nav.getCurrentlyPlayingServiceOrGroup()
    if service is not None and ref is not None:
        seek = service.seek()
        if seek:
            pos = seek.getPlayPosition()
            if not pos[0]:
                key = ref.toString()
                lru = int(time())
                l = seek.getLength()
                if l:
                    l = l[1]
                else:
                    l = None
                resumePointCache[key] = [lru, pos[1], l]
                if len(resumePointCache) > 50:
                    candidate = key
                    for k, v in resumePointCache.items():
                        if v[0] < lru:
                            candidate = k

                    del resumePointCache[candidate]
                if lru - resumePointCacheLast > 3600:
                    saveResumePoints()


def delResumePoint(ref):
    try:
        del resumePointCache[ref.toString()]
    except KeyError:
        pass

    if int(time()) - resumePointCacheLast > 3600:
        saveResumePoints()


def getResumePoint(session):
    ref = session.nav.getCurrentlyPlayingServiceOrGroup()
    if ref is not None and ref.type != 1:
        try:
            entry = resumePointCache[ref.toString()]
            entry[0] = int(time())
            return entry[1]
        except KeyError:
            return


def saveResumePoints():
    global resumePointCacheLast
    import cPickle
    try:
        f = open('/home/root/resumepoints.pkl', 'wb')
        cPickle.dump(resumePointCache, f, cPickle.HIGHEST_PROTOCOL)
    except Exception as ex:
        print '[InfoBar] Failed to write resumepoints:', ex

    resumePointCacheLast = int(time())


def loadResumePoints():
    import cPickle
    try:
        return cPickle.load(open('/home/root/resumepoints.pkl', 'rb'))
    except Exception as ex:
        print '[InfoBar] Failed to load resumepoints:', ex
        return {}


resumePointCache = loadResumePoints()
resumePointCacheLast = int(time())

class InfoBarDish():

    def __init__(self):
        self.dishDialog = self.session.instantiateDialog(Dish)


class InfoBarUnhandledKey():

    def __init__(self):
        self.unhandledKeyDialog = self.session.instantiateDialog(UnhandledKey)
        self.hideUnhandledKeySymbolTimer = eTimer()
        self.hideUnhandledKeySymbolTimer.callback.append(self.unhandledKeyDialog.hide)
        self.checkUnusedTimer = eTimer()
        self.checkUnusedTimer.callback.append(self.checkUnused)
        self.onLayoutFinish.append(self.unhandledKeyDialog.hide)
        eActionMap.getInstance().bindAction('', -maxint - 1, self.actionA)
        eActionMap.getInstance().bindAction('', maxint, self.actionB)
        self.flags = 2
        self.uflags = 0

    def actionA(self, key, flag):
        self.unhandledKeyDialog.hide()
        if flag != 4:
            if self.flags & 2:
                self.flags = self.uflags = 0
            self.flags |= 1 << flag
            if flag == 1:
                self.checkUnusedTimer.start(0, True)
        return 0

    def actionB(self, key, flag):
        if flag != 4:
            self.uflags |= 1 << flag

    def checkUnused(self):
        if self.flags == self.uflags:
            self.unhandledKeyDialog.show()
            self.hideUnhandledKeySymbolTimer.start(2000, True)


class InfoBarScreenSaver():

    def __init__(self):
        self.onExecBegin.append(self.__onExecBegin)
        self.onExecEnd.append(self.__onExecEnd)
        self.screenSaverTimer = eTimer()
        self.screenSaverTimer.callback.append(self.screensaverTimeout)
        self.screensaver = self.session.instantiateDialog(ScreenSaver.Screensaver)
        self.onLayoutFinish.append(self.__layoutFinished)

    def __layoutFinished(self):
        self.screensaver.hide()

    def __onExecBegin(self):
        self.ScreenSaverTimerStart()

    def __onExecEnd(self):
        if self.screensaver.shown:
            self.screensaver.hide()
            eActionMap.getInstance().unbindAction('', self.keypressScreenSaver)
        self.screenSaverTimer.stop()

    def ScreenSaverTimerStart(self):
        time = int(config.usage.screen_saver.value)
        flag = self.seekstate[0]
        if not flag:
            ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
            if ref and not (hasattr(self.session, 'pipshown') and self.session.pipshown):
                ref = ref.toString().split(':')
                flag = ref[2] == '2' or os.path.splitext(ref[10])[1].lower() in AUDIO_EXTENSIONS
        if time and flag:
            self.screenSaverTimer.startLongTimer(time)
        else:
            self.screenSaverTimer.stop()

    def screensaverTimeout(self):
        if self.execing and not Standby.inStandby and not Standby.inTryQuitMainloop:
            self.hide()
            if hasattr(self, 'pvrStateDialog'):
                self.pvrStateDialog.hide()
            self.screensaver.show()
            eActionMap.getInstance().bindAction('', -maxint - 1, self.keypressScreenSaver)

    def keypressScreenSaver(self, key, flag):
        if flag:
            self.screensaver.hide()
            self.show()
            self.ScreenSaverTimerStart()
            eActionMap.getInstance().unbindAction('', self.keypressScreenSaver)


class HideVBILine(Screen):
    skin = '<screen position="0,0" size="%s,%s" backgroundColor="0" flags="wfNoBorder"/>' % (getDesktop(0).size().width() * 2 / 3, getDesktop(0).size().height() / 360 + 1)

    def __init__(self, session):
        Screen.__init__(self, session)


class SecondInfoBar(Screen):

    def __init__(self, session, skinName):
        Screen.__init__(self, session)
        self.skinName = skinName


class InfoBarShowHide(InfoBarScreenSaver):
    STATE_HIDDEN = 0
    STATE_HIDING = 1
    STATE_SHOWING = 2
    STATE_SHOWN = 3
    FLAG_HIDE_VBI = 512
    FLAG_CENTER_DVB_SUBS = 2048

    def __init__(self):
        self['ShowHideActions'] = ActionMap(['InfobarShowHideActions'], {'toggleShow': self.okButtonCheck,
         'hide': self.keyHide,
         'toggleShowLong': self.toggleShowLong,
         'hideLong': self.hideLong}, 1)
        self.__event_tracker = ServiceEventTracker(screen=self, eventmap={iPlayableService.evStart: self.serviceStarted})
        InfoBarScreenSaver.__init__(self)
        self.__state = self.STATE_SHOWN
        self.__locked = 0
        self.hideTimer = eTimer()
        self.hideTimer.callback.append(self.doTimerHide)
        self.hideTimer.start(5000, True)
        self.onShow.append(self.__onShow)
        self.onHide.append(self.__onHide)
        self.onShowHideNotifiers = []
        self.actualSecondInfoBarScreen = None
        if isStandardInfoBar(self):
            self.secondInfoBarScreen = self.session.instantiateDialog(SecondInfoBar, 'SecondInfoBar')
            self.secondInfoBarScreen.show()
            self.secondInfoBarScreenSimple = self.session.instantiateDialog(SecondInfoBar, 'SecondInfoBarSimple')
            self.secondInfoBarScreenSimple.show()
            self.actualSecondInfoBarScreen = config.usage.show_simple_second_infobar.value and self.secondInfoBarScreenSimple.skinAttributes and self.secondInfoBarScreenSimple or self.secondInfoBarScreen
        self.hideVBILineScreen = self.session.instantiateDialog(HideVBILine)
        self.hideVBILineScreen.show()
        self.onLayoutFinish.append(self.__layoutFinished)
        self.onExecBegin.append(self.__onExecBegin)

    def __onExecBegin(self):
        self.clearScreenPath()
        self.showHideVBI()

    def __layoutFinished(self):
        if self.actualSecondInfoBarScreen:
            self.secondInfoBarScreen.hide()
            self.secondInfoBarScreenSimple.hide()
        self.hideVBILineScreen.hide()

    def __onShow(self):
        self.__state = self.STATE_SHOWN
        for x in self.onShowHideNotifiers:
            x(True)

        self.startHideTimer()

    def __onHide(self):
        self.__state = self.STATE_HIDDEN
        if self.actualSecondInfoBarScreen:
            self.actualSecondInfoBarScreen.hide()
        for x in self.onShowHideNotifiers:
            x(False)

    def toggleShowLong(self):
        if not config.usage.ok_is_channelselection.value:
            self.toggleSecondInfoBar()

    def hideLong(self):
        if config.usage.ok_is_channelselection.value:
            self.toggleSecondInfoBar()

    def toggleSecondInfoBar(self):
        if self.actualSecondInfoBarScreen and not self.shown and not self.actualSecondInfoBarScreen.shown and self.secondInfoBarScreenSimple.skinAttributes and self.secondInfoBarScreen.skinAttributes:
            self.actualSecondInfoBarScreen.hide()
            config.usage.show_simple_second_infobar.value = not config.usage.show_simple_second_infobar.value
            config.usage.show_simple_second_infobar.save()
            self.actualSecondInfoBarScreen = config.usage.show_simple_second_infobar.value and self.secondInfoBarScreenSimple or self.secondInfoBarScreen
            self.showSecondInfoBar()

    def keyHide(self):
        if self.__state == self.STATE_HIDDEN and self.session.pipshown and 'popup' in config.usage.pip_hideOnExit.value:
            if config.usage.pip_hideOnExit.value == 'popup':
                self.session.openWithCallback(self.hidePipOnExitCallback, MessageBox, _('Disable Picture in Picture'), simple=True)
            else:
                self.hidePipOnExitCallback(True)
        elif config.usage.ok_is_channelselection.value and hasattr(self, 'openServiceList'):
            self.toggleShow()
        elif self.__state == self.STATE_SHOWN:
            self.hide()

    def hidePipOnExitCallback(self, answer):
        if answer == True:
            self.showPiP()

    def connectShowHideNotifier(self, fnc):
        if fnc not in self.onShowHideNotifiers:
            self.onShowHideNotifiers.append(fnc)

    def disconnectShowHideNotifier(self, fnc):
        if fnc in self.onShowHideNotifiers:
            self.onShowHideNotifiers.remove(fnc)

    def serviceStarted(self):
        if self.execing:
            if config.usage.show_infobar_on_zap.value:
                self.doShow()
        self.showHideVBI()

    def startHideTimer(self):
        if self.__state == self.STATE_SHOWN and not self.__locked:
            self.hideTimer.stop()
            if self.actualSecondInfoBarScreen and self.actualSecondInfoBarScreen.shown:
                idx = config.usage.show_second_infobar.index - 1
            else:
                idx = config.usage.infobar_timeout.index
            if idx:
                self.hideTimer.startLongTimer(idx)

    def doShow(self):
        self.show()
        self.startHideTimer()

    def doTimerHide(self):
        self.hideTimer.stop()
        if self.__state == self.STATE_SHOWN:
            self.hide()

    def okButtonCheck(self):
        if config.usage.ok_is_channelselection.value and hasattr(self, 'openServiceList'):
            if isinstance(self, InfoBarTimeshift) and self.timeshiftEnabled() and isinstance(self, InfoBarSeek) and self.seekstate == self.SEEK_STATE_PAUSE:
		     return
            self.openServiceList()
        else:
            self.toggleShow()

    def toggleShow(self):
        if self.__state == self.STATE_HIDDEN:
            self.showFirstInfoBar()
        else:
            self.showSecondInfoBar()

    def showSecondInfoBar(self):
        if isStandardInfoBar(self) and config.usage.show_second_infobar.value == 'EPG':
            if not (hasattr(self, 'hotkeyGlobal') and self.hotkeyGlobal('info') != 0):
                self.showDefaultEPG()
        elif self.actualSecondInfoBarScreen and config.usage.show_second_infobar.value and not self.actualSecondInfoBarScreen.shown:
            self.show()
            self.actualSecondInfoBarScreen.show()
            self.startHideTimer()
        else:
            self.hide()
            self.hideTimer.stop()

    def showFirstInfoBar(self):
        if self.__state == self.STATE_HIDDEN or self.actualSecondInfoBarScreen and self.actualSecondInfoBarScreen.shown:
            self.actualSecondInfoBarScreen and self.actualSecondInfoBarScreen.hide()
            self.show()
        else:
            self.hide()
            self.hideTimer.stop()

    def lockShow(self):
        self.__locked = self.__locked + 1
        if self.execing:
            self.show()
            self.hideTimer.stop()

    def unlockShow(self):
        self.__locked = self.__locked - 1
        if self.execing:
            self.startHideTimer()

    def checkHideVBI(self):
        service = self.session.nav.getCurrentlyPlayingServiceReference()
        servicepath = service and service.getPath()
        if servicepath and servicepath.startswith('/'):
            if service.toString().startswith('1:'):
                info = eServiceCenter.getInstance().info(service)
                service = info and info.getInfoString(service, iServiceInformation.sServiceref)
                return service and eDVBDB.getInstance().getFlag(eServiceReference(service)) & self.FLAG_HIDE_VBI and True
            else:
                return '.hidvbi.' in servicepath.lower()
        service = self.session.nav.getCurrentService()
        info = service and service.info()
        return info and info.getInfo(iServiceInformation.sHideVBI)

    def showHideVBI(self):
        if self.checkHideVBI():
            self.hideVBILineScreen.show()
        else:
            self.hideVBILineScreen.hide()

    def ToggleHideVBI(self):
	service = self.session.nav.getCurrentlyPlayingServiceReference()
	servicepath = service and service.getPath()
	if not servicepath:
	    if eDVBDB.getInstance().getFlag(service) & self.FLAG_HIDE_VBI:
	       eDVBDB.getInstance().removeFlag(service, self.FLAG_HIDE_VBI)
	    else:
	       eDVBDB.getInstance().addFlag(service, self.FLAG_HIDE_VBI)
	    eDVBDB.getInstance().reloadBouquets()
	    self.showHideVBI()

class BufferIndicator(Screen):

    def __init__(self, session):
        Screen.__init__(self, session)
        self['status'] = Label()
        self.mayShow = False
        self.__event_tracker = ServiceEventTracker(screen=self, eventmap={iPlayableService.evBuffering: self.bufferChanged,
         iPlayableService.evStart: self.__evStart,
         iPlayableService.evGstreamerPlayStarted: self.__evGstreamerPlayStarted})

    def bufferChanged(self):
        if self.mayShow:
            service = self.session.nav.getCurrentService()
            info = service and service.info()
            if info:
                value = info.getInfo(iServiceInformation.sBuffer)
                if value and value != 100:
                    self['status'].setText(_('Buffering %d%%') % value)
                    if not self.shown:
                        self.show()

    def __evStart(self):
        self.mayShow = True
        self.hide()

    def __evGstreamerPlayStarted(self):
        self.mayShow = False
        self.hide()


class InfoBarBuffer():

    def __init__(self):
        self.bufferScreen = self.session.instantiateDialog(BufferIndicator)
        self.bufferScreen.hide()


class NumberZap(Screen):

    def quit(self):
        self.Timer.stop()
        self.close()

    def keyOK(self):
        self.Timer.stop()
        self.close(self.service, self.bouquet)

    def handleServiceName(self):
        if self.searchNumber:
            self.service, self.bouquet = self.searchNumber(int(self['number'].getText()))
            self['servicename'].text = self['servicename_summary'].text = ServiceReference(self.service).getServiceName()
            if not self.startBouquet:
                self.startBouquet = self.bouquet

    def keyBlue(self):
        self.startTimer()
        if self.searchNumber:
            if self.startBouquet == self.bouquet:
                self.service, self.bouquet = self.searchNumber(int(self['number'].getText()), firstBouquetOnly=True)
            else:
                self.service, self.bouquet = self.searchNumber(int(self['number'].getText()))
            self['servicename'].text = self['servicename_summary'].text = ServiceReference(self.service).getServiceName()

    def keyNumberGlobal(self, number):
        self.startTimer(repeat=True)
        self.numberString = self.numberString + str(number)
        self['number'].text = self['number_summary'].text = self.numberString
        self.handleServiceName()
        if len(self.numberString) >= 5:
            self.keyOK()

    def __init__(self, session, number, searchNumberFunction = None):
        Screen.__init__(self, session)
        self.numberString = str(number)
        self.searchNumber = searchNumberFunction
        self.startBouquet = None
        self['channel'] = Label(_('Channel:'))
        self['number'] = Label(self.numberString)
        self['servicename'] = Label()
        self['channel_summary'] = StaticText(_('Channel:'))
        self['number_summary'] = StaticText(self.numberString)
        self['servicename_summary'] = StaticText()
        self.handleServiceName()
        self['actions'] = NumberActionMap(['SetupActions', 'ShortcutActions'], {'cancel': self.quit,
         'ok': self.keyOK,
         'blue': self.keyBlue,
         '1': self.keyNumberGlobal,
         '2': self.keyNumberGlobal,
         '3': self.keyNumberGlobal,
         '4': self.keyNumberGlobal,
         '5': self.keyNumberGlobal,
         '6': self.keyNumberGlobal,
         '7': self.keyNumberGlobal,
         '8': self.keyNumberGlobal,
         '9': self.keyNumberGlobal,
         '0': self.keyNumberGlobal})
        self.Timer = eTimer()
        self.Timer.callback.append(self.endTimer)
        self.Timer.start(250)
        self.startTimer()

    def startTimer(self, repeat = False):
        self.timer_target = repeat and self.timer_counter < 6 and [4,
         4,
         4,
         5,
         8,
         10][self.timer_counter] or 12
        self.timer_counter = 0

    def endTimer(self):
        self.timer_counter += 1
        if self.timer_counter > self.timer_target:
            self.keyOK()


class InfoBarNumberZap():

    def __init__(self):
        self['NumberActions'] = NumberActionMap(['NumberActions'], {'1': self.keyNumberGlobal,
         '2': self.keyNumberGlobal,
         '3': self.keyNumberGlobal,
         '4': self.keyNumberGlobal,
         '5': self.keyNumberGlobal,
         '6': self.keyNumberGlobal,
         '7': self.keyNumberGlobal,
         '8': self.keyNumberGlobal,
         '9': self.keyNumberGlobal,
         '0': self.keyNumberGlobal})

    def keyNumberGlobal(self, number):
        if number == 0:
            if isinstance(self, InfoBarPiP) and self.pipHandles0Action():
                self.pipDoHandle0Action()
            elif len(self.servicelist.history) > 1:
                self.checkTimeshiftRunning(self.recallPrevService)
        else:
            if self.has_key('TimeshiftActions') and self.timeshiftEnabled():
                ts = self.getTimeshift()
                if ts and ts.isTimeshiftActive():
                    return
            self.session.openWithCallback(self.numberEntered, NumberZap, number, self.searchNumber)

    def recallPrevService(self, reply):
        if reply:
            self.servicelist.recallPrevService()

    def numberEntered(self, service = None, bouquet = None):
        if service:
            self.selectAndStartService(service, bouquet)

    def searchNumberHelper(self, serviceHandler, num, bouquet):
        servicelist = serviceHandler.list(bouquet)
        if servicelist:
            serviceIterator = servicelist.getNext()
            while serviceIterator.valid():
                if num == serviceIterator.getChannelNum():
                    return serviceIterator
                serviceIterator = servicelist.getNext()

    def searchNumber(self, number, firstBouquetOnly = False, bouquet = None):
        bouquet = bouquet or self.servicelist.getRoot()
        service = None
        serviceHandler = eServiceCenter.getInstance()
        if not firstBouquetOnly:
            service = self.searchNumberHelper(serviceHandler, number, bouquet)
        if config.usage.multibouquet.value and not service:
            bouquet = self.servicelist.bouquet_root
            bouquetlist = serviceHandler.list(bouquet)
            if bouquetlist:
                bouquet = bouquetlist.getNext()
                while bouquet.valid():
                    if bouquet.flags & eServiceReference.isDirectory and not bouquet.flags & eServiceReference.isInvisible:
                        service = self.searchNumberHelper(serviceHandler, number, bouquet)
                        if service:
                            playable = not service.flags & (eServiceReference.isMarker | eServiceReference.isDirectory) or service.flags & eServiceReference.isNumberedMarker
                            if not playable:
                                service = None
                            break
                        if config.usage.alternative_number_mode.value or firstBouquetOnly:
                            break
                    bouquet = bouquetlist.getNext()

        return (service, bouquet)

    def selectAndStartService(self, service, bouquet):
        if service and not service.flags & eServiceReference.isMarker:
            if self.servicelist.getRoot() != bouquet:
                self.servicelist.clearPath()
                if self.servicelist.bouquet_root != bouquet:
                    self.servicelist.enterPath(self.servicelist.bouquet_root)
                self.servicelist.enterPath(bouquet)
            self.servicelist.setCurrentSelection(service)
            self.servicelist.zap(enable_pipzap=True)
            self.servicelist.correctChannelNumber()
            self.servicelist.startRoot = None

    def zapToNumber(self, number):
        service, bouquet = self.searchNumber(number)
        self.selectAndStartService(service, bouquet)


config.misc.initialchannelselection = ConfigBoolean(default=True)

class InfoBarChannelSelection():

    def __init__(self):
        self.servicelist = self.session.instantiateDialog(ChannelSelection)
        if config.misc.initialchannelselection.value:
            self.onShown.append(self.firstRun)
        self['ChannelSelectActions'] = HelpableActionMap(self, 'InfobarChannelSelection', {'keyUp': (self.keyUpCheck, self.getKeyUpHelptext),
         'keyDown': (self.keyDownCheck, self.getKeyDownHelpText),
         'keyLeft': (self.keyLeftCheck, self.getKeyLeftHelptext),
         'keyRight': (self.keyRightCheck, self.getKeyRightHelptext),
         'historyBack': (self.historyBack, _('Switch to previous channel in history')),
         'historyNext': (self.historyNext, _('Switch to next channel in history')),
         'keyChannelUp': (self.keyChannelUpCheck, self.getKeyChannelUpHelptext),
         'keyChannelDown': (self.keyChannelDownCheck, self.getKeyChannelDownHelptext)})

    def showTvChannelList(self, zap = False):
        self.servicelist.setModeTv()
        if zap:
            self.servicelist.zap()

    def showRadioChannelList(self, zap = False):
        self.servicelist.setModeRadio()
        if zap:
            self.servicelist.zap()

    def firstRun(self):
        self.onShown.remove(self.firstRun)
        config.misc.initialchannelselection.value = False
        config.misc.initialchannelselection.save()
        self.switchChannelDown()

    def historyBack(self):
        if config.usage.historymode.getValue() == '0':
            self.servicelist.historyBack()
        else:
            self.servicelist.historyZap(-1)

    def historyNext(self):
        if config.usage.historymode.getValue() == '0':
            self.servicelist.historyNext()
        else:
            self.servicelist.historyZap(+1)

    def historyNextCheckTimeshiftCallback(self, answer):
        if answer:
            self.servicelist.historyNext()

    def keyUpCheck(self):
        if config.usage.oldstyle_zap_controls.value:
            self.zapDown()
        elif config.usage.volume_instead_of_channelselection.value:
            VolumeControl.instance and VolumeControl.instance.volUp()
        else:
            self.switchChannelUp()

    def keyDownCheck(self):
        if config.usage.oldstyle_zap_controls.value:
            self.zapUp()
        elif config.usage.volume_instead_of_channelselection.value:
            VolumeControl.instance and VolumeControl.instance.volDown()
        else:
            self.switchChannelDown()

    def keyLeftCheck(self):
        if config.usage.oldstyle_zap_controls.value:
            if config.usage.volume_instead_of_channelselection.value:
                VolumeControl.instance and VolumeControl.instance.volDown()
            else:
                self.switchChannelUp()
        else:
            self.zapUp()

    def keyRightCheck(self):
        if config.usage.oldstyle_zap_controls.value:
            if config.usage.volume_instead_of_channelselection.value:
                VolumeControl.instance and VolumeControl.instance.volUp()
            else:
                self.switchChannelDown()
        else:
            self.zapDown()

    def keyChannelUpCheck(self):
        if config.usage.zap_with_ch_buttons.value:
            self.zapDown()
        else:
            self.openServiceList()

    def keyChannelDownCheck(self):
        if config.usage.zap_with_ch_buttons.value:
            self.zapUp()
        else:
            self.openServiceList()

    def getKeyUpHelptext(self):
        if config.usage.oldstyle_zap_controls.value:
            value = _('Switch to next channel')
        elif config.usage.volume_instead_of_channelselection.value:
            value = _('Volume up')
        else:
            value = _('Open service list')
            if 'keep' not in config.usage.servicelist_cursor_behavior.value:
                value += ' ' + _('and select previous channel')
        return value

    def getKeyDownHelpText(self):
        if config.usage.oldstyle_zap_controls.value:
            value = _('Switch to previous channel')
        elif config.usage.volume_instead_of_channelselection.value:
            value = _('Volume down')
        else:
            value = _('Open service list')
            if 'keep' not in config.usage.servicelist_cursor_behavior.value:
                value += ' ' + _('and select next channel')
        return value

    def getKeyLeftHelptext(self):
        if config.usage.oldstyle_zap_controls.value:
            if config.usage.volume_instead_of_channelselection.value:
                value = _('Volume down')
            else:
                value = _('Open service list')
                if 'keep' not in config.usage.servicelist_cursor_behavior.value:
                    value += ' ' + _('and select previous channel')
        else:
            value = _('Switch to previous channel')
        return value

    def getKeyRightHelptext(self):
        if config.usage.oldstyle_zap_controls.value:
            if config.usage.volume_instead_of_channelselection.value:
                value = _('Volume up')
            else:
                value = _('Open service list')
                if 'keep' not in config.usage.servicelist_cursor_behavior.value:
                    value += ' ' + _('and select next channel')
        else:
            value = _('Switch to next channel')
        return value

    def getKeyChannelUpHelptext(self):
        return config.usage.zap_with_ch_buttons.value and _('Switch to next channel') or _('Open service list')

    def getKeyChannelDownHelptext(self):
        return config.usage.zap_with_ch_buttons.value and _('Switch to previous channel') or _('Open service list')

    def switchChannelUp(self):
        if 'keep' not in config.usage.servicelist_cursor_behavior.value:
            self.servicelist.moveUp()
        self.session.execDialog(self.servicelist)

    def switchChannelDown(self):
        if 'keep' not in config.usage.servicelist_cursor_behavior.value:
            self.servicelist.moveDown()
        self.session.execDialog(self.servicelist)

    def zapUp(self):
        if self.servicelist.inBouquet():
            prev = self.servicelist.getCurrentSelection()
            if prev:
                prev = prev.toString()
                while True:
                    if config.usage.quickzap_bouquet_change.value:
                        if self.servicelist.atBegin():
                            self.servicelist.prevBouquet()
                    self.servicelist.moveUp()
                    cur = self.servicelist.getCurrentSelection()
                    if cur:
                        if self.servicelist.dopipzap:
                            isPlayable = self.session.pip.isPlayableForPipService(cur)
                        else:
                            isPlayable = isPlayableForCur(cur)
                    if cur and (cur.toString() == prev or isPlayable):
                        break

        else:
            self.servicelist.moveUp()
        self.servicelist.zap(enable_pipzap=True)

    def zapDown(self):
        if self.servicelist.inBouquet():
            prev = self.servicelist.getCurrentSelection()
            if prev:
                prev = prev.toString()
                while True:
                    if config.usage.quickzap_bouquet_change.value and self.servicelist.atEnd():
                        self.servicelist.nextBouquet()
                    else:
                        self.servicelist.moveDown()
                    cur = self.servicelist.getCurrentSelection()
                    if cur:
                        if self.servicelist.dopipzap:
                            isPlayable = self.session.pip.isPlayableForPipService(cur)
                        else:
                            isPlayable = isPlayableForCur(cur)
                    if cur and (cur.toString() == prev or isPlayable):
                        break

        else:
            self.servicelist.moveDown()
        self.servicelist.zap(enable_pipzap=True)

    def openFavouritesList(self):
        self.servicelist.showFavourites()
        self.openServiceList()

    def openServiceList(self):
        self.session.execDialog(self.servicelist)


class InfoBarMenu():

    def __init__(self):
        self["MenuActions"] = HelpableActionMap(self, "InfobarMenuActions",
  			{
  				"mainMenu": (self.mainMenu, _("Enter main menu...")),
				"toggleAspectRatio": (self.toggleAspectRatio, _("Toggle aspect ratio...")),
  			})
        self.session.infobar = None

    def mainMenu(self):
        print 'loading mainmenu XML...'
        menu = mdom.getroot()
        self.session.infobar = self
        self.session.openWithCallback(self.mainMenuClosed, MainMenu, menu)

    def mainMenuClosed(self, *val):
        self.session.infobar = None

    def toggleAspectRatio(self):
 		ASPECT = [ "auto", "16:9", "4:3" ]
 		ASPECT_MSG = { "auto":"Auto", "16:9":"16:9", "4:3":"4:3" }
 		if config.av.aspect.value in ASPECT:
 			index = ASPECT.index(config.av.aspect.value)
 			config.av.aspect.value = ASPECT[(index+1)%3]
 		else:
 			config.av.aspect.value = "auto"
 		config.av.aspect.save()
 		self.session.open(MessageBox, _("AV aspect is %s." % ASPECT_MSG[config.av.aspect.value]), MessageBox.TYPE_INFO, timeout=5)

class InfoBarSimpleEventView():

    def __init__(self):
        self['EPGActions'] = HelpableActionMap(self, 'InfobarEPGActions', {'showEventInfo': (self.openEventView, _('Show event details')),
         'showEventInfoSingleEPG': (self.openEventView, _('Show event details')),
         'showInfobarOrEpgWhenInfobarAlreadyVisible': self.showEventInfoWhenNotVisible})

    def showEventInfoWhenNotVisible(self):
        if self.shown:
            self.openEventView()
        else:
            self.toggleShow()
            return 1

    def openEventView(self):
        epglist = []
        self.epglist = epglist
        service = self.session.nav.getCurrentService()
        ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
        info = service.info()
        ptr = info.getEvent(0)
        if ptr:
            epglist.append(ptr)
        ptr = info.getEvent(1)
        if ptr:
            epglist.append(ptr)
        if epglist:
            self.session.open(EventViewSimple, epglist[0], ServiceReference(ref), self.eventViewCallback)

    def eventViewCallback(self, setEvent, setService, val):
        epglist = self.epglist
        if len(epglist) > 1:
            tmp = epglist[0]
            epglist[0] = epglist[1]
            epglist[1] = tmp
            setEvent(epglist[0])


class SimpleServicelist():

    def __init__(self, services):
        self.setServices(services)

    def setServices(self, services):
        self.services = services
        self.length = len(services)
        self.current = 0

    def selectService(self, service):
        if not self.length:
            self.current = -1
            return False
        self.current = 0
        while self.services[self.current].ref != service:
            self.current += 1
            if self.current >= self.length:
                return False

        return True

    def nextService(self):
        if not self.length:
            return
        if self.current + 1 < self.length:
            self.current += 1
        else:
            self.current = 0

    def prevService(self):
        if not self.length:
            return
        if self.current - 1 > -1:
            self.current -= 1
        else:
            self.current = self.length - 1

    def currentService(self):
        if not self.length or self.current >= self.length:
            return None
        return self.services[self.current]


class InfoBarEPG():

    def __init__(self):
        self.is_now_next = False
        self.dlg_stack = []
        self.bouquetSel = None
        self.eventView = None
        self.epglist = []
        self.__event_tracker = ServiceEventTracker(screen=self, eventmap={iPlayableService.evUpdatedEventInfo: self.__evEventInfoChanged})
        self['EPGActions'] = HelpableActionMap(self, 'InfobarEPGActions', {'showEventInfo': (self.showDefaultEPG, _('Show EPG...')),
         'showEventInfoSingleEPG': (self.showSingleEPG, _('Show single service EPG')),
         'showEventInfoMultiEPG': (self.showMultiEPG, _('Show multi channel EPG')),
         'showInfobarOrEpgWhenInfobarAlreadyVisible': self.showEventInfoWhenNotVisible})

    def getEPGPluginList(self, getAll = False):
        pluginlist = [ (p.name, boundFunction(self.runPlugin, p), p.path) for p in plugins.getPlugins(where=PluginDescriptor.WHERE_EVENTINFO) if 'selectedevent' not in p.__call__.func_code.co_varnames ] or []
        from Components.ServiceEventTracker import InfoBarCount
        if getAll or InfoBarCount == 1:
            pluginlist.append((_('Show EPG for current channel...'), self.openSingleServiceEPG, 'current_channel'))
        pluginlist.append((_('Multi EPG'), self.openMultiServiceEPG, 'multi_epg'))
        pluginlist.append((_('Current event EPG'), self.openEventView, 'event_epg'))
        return pluginlist

    def showEventInfoWhenNotVisible(self):
        if self.shown:
            self.openEventView()
        else:
            self.toggleShow()
            return 1

    def zapToService(self, service, preview = False, zapback = False):
        if self.servicelist.startServiceRef is None:
            self.servicelist.startServiceRef = self.session.nav.getCurrentlyPlayingServiceOrGroup()
        if service is not None:
            if self.servicelist.getRoot() != self.epg_bouquet:
                self.servicelist.clearPath()
                if self.servicelist.bouquet_root != self.epg_bouquet:
                    self.servicelist.enterPath(self.servicelist.bouquet_root)
                self.servicelist.enterPath(self.epg_bouquet)
            self.servicelist.setCurrentSelection(service)
        if not zapback or preview:
            self.servicelist.zap(enable_pipzap=True)
        if (self.servicelist.dopipzap or zapback) and not preview:
            self.servicelist.zapBack()
        if not preview:
            self.servicelist.startServiceRef = None
            self.servicelist.startRoot = None

    def getBouquetServices(self, bouquet):
        services = []
        servicelist = eServiceCenter.getInstance().list(bouquet)
        if servicelist is not None:
            while True:
                service = servicelist.getNext()
                if not service.valid():
                    break
                if service.flags & (eServiceReference.isDirectory | eServiceReference.isMarker):
                    continue
                services.append(ServiceReference(service))

        return services

    def openBouquetEPG(self, bouquet, withCallback = True):
        services = self.getBouquetServices(bouquet)
        if services:
            self.epg_bouquet = bouquet
            if withCallback:
                self.dlg_stack.append(self.session.openWithCallback(self.closed, EPGSelection, services, self.zapToService, None, self.changeBouquetCB))
            else:
                self.session.open(EPGSelection, services, self.zapToService, None, self.changeBouquetCB)

    def changeBouquetCB(self, direction, epg):
        if self.bouquetSel:
            if direction > 0:
                self.bouquetSel.down()
            else:
                self.bouquetSel.up()
            bouquet = self.bouquetSel.getCurrent()
            services = self.getBouquetServices(bouquet)
            if services:
                self.epg_bouquet = bouquet
                epg.setServices(services)

    def selectBouquet(self, bouquetref, epg):
        services = self.getBouquetServices(bouquetref)
        if services:
            self.epg_bouquet = bouquetref
            self.serviceSel.setServices(services)
            epg.setServices(services)

    def setService(self, service):
        if service:
            self.serviceSel.selectService(service)

    def closed(self, ret = False):
        closedScreen = self.dlg_stack.pop()
        if self.bouquetSel and closedScreen == self.bouquetSel:
            self.bouquetSel = None
        elif self.eventView and closedScreen == self.eventView:
            self.eventView = None
        if ret:
            dlgs = len(self.dlg_stack)
            if dlgs > 0:
                self.dlg_stack[dlgs - 1].close(dlgs > 1)

    def openMultiServiceEPG(self, withCallback = True):
        bouquets = self.servicelist.getBouquetList()
        if bouquets is None:
            cnt = 0
        else:
            cnt = len(bouquets)
        if config.usage.multiepg_ask_bouquet.value:
            self.openMultiServiceEPGAskBouquet(bouquets, cnt, withCallback)
        else:
            self.openMultiServiceEPGSilent(bouquets, cnt, withCallback)

    def openMultiServiceEPGAskBouquet(self, bouquets, cnt, withCallback):
        if cnt > 1:
            if withCallback:
                self.bouquetSel = self.session.openWithCallback(self.closed, BouquetSelector, bouquets, self.openBouquetEPG, enableWrapAround=True)
                self.dlg_stack.append(self.bouquetSel)
            else:
                self.bouquetSel = self.session.open(BouquetSelector, bouquets, self.openBouquetEPG, enableWrapAround=True)
        elif cnt == 1:
            self.openBouquetEPG(bouquets[0][1], withCallback)

    def openMultiServiceEPGSilent(self, bouquets, cnt, withCallback):
        root = self.servicelist.getRoot()
        rootstr = root.toCompareString()
        current = 0
        for bouquet in bouquets:
            if bouquet[1].toCompareString() == rootstr:
                break
            current += 1

        if current >= cnt:
            current = 0
        if cnt > 1:
            self.bouquetSel = SilentBouquetSelector(bouquets, True, self.servicelist.getBouquetNumOffset(root))
        if cnt >= 1:
            self.openBouquetEPG(root, withCallback)

    def changeServiceCB(self, direction, epg):
        if self.serviceSel:
            if direction > 0:
                self.serviceSel.nextService()
            else:
                self.serviceSel.prevService()
            epg.setService(self.serviceSel.currentService())

    def SingleServiceEPGClosed(self, ret = False):
        self.serviceSel = None

    def openSingleServiceEPG(self):
        ref = self.servicelist.getCurrentSelection()
        if ref:
            if self.servicelist.getMutableList():
                current_path = self.servicelist.getRoot()
                services = self.getBouquetServices(current_path)
                self.serviceSel = SimpleServicelist(services)
                if self.serviceSel.selectService(ref):
                    self.epg_bouquet = current_path
                    self.session.openWithCallback(self.SingleServiceEPGClosed, EPGSelection, ref, self.zapToService, serviceChangeCB=self.changeServiceCB, parent=self)
                else:
                    self.session.openWithCallback(self.SingleServiceEPGClosed, EPGSelection, ref)
            else:
                self.session.open(EPGSelection, ref)

    def runPlugin(self, plugin):
        plugin(session=self.session, servicelist=self.servicelist)

    def showEventInfoPlugins(self):
        pluginlist = self.getEPGPluginList()
        if pluginlist:
            self.session.openWithCallback(self.EventInfoPluginChosen, ChoiceBox, title=_('Please choose an extension...'), list=pluginlist, skin_name='EPGExtensionsList', reorderConfig='eventinfo_order', windowTitle=_('Events info menu'))
        else:
            self.openSingleServiceEPG()

    def EventInfoPluginChosen(self, answer):
        if answer is not None:
            answer[1]()

    def openSimilarList(self, eventid, refstr):
        self.session.open(EPGSelection, refstr, None, eventid)

    def getNowNext(self):
        epglist = []
        service = self.session.nav.getCurrentService()
        info = service and service.info()
        ptr = info and info.getEvent(0)
        if ptr and ptr.getEventName() != '':
            epglist.append(ptr)
        ptr = info and info.getEvent(1)
        if ptr and ptr.getEventName() != '':
            epglist.append(ptr)
        self.epglist = epglist

    def __evEventInfoChanged(self):
        if self.is_now_next and len(self.dlg_stack) == 1:
            self.getNowNext()
            if self.eventView and self.epglist:
                self.eventView.setEvent(self.epglist[0])

    def showDefaultEPG(self):
        self.openEventView()

    def showSingleEPG(self):
        self.openSingleServiceEPG()

    def showMultiEPG(self):
        self.openMultiServiceEPG()

    def openEventView(self):
        from Components.ServiceEventTracker import InfoBarCount
        if InfoBarCount > 1:
            epglist = []
            self.epglist = epglist
            service = self.session.nav.getCurrentService()
            ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
            info = service.info()
            ptr = info.getEvent(0)
            if ptr:
                epglist.append(ptr)
            ptr = info.getEvent(1)
            if ptr:
                epglist.append(ptr)
            if epglist:
                self.session.open(EventViewEPGSelect, epglist[0], ServiceReference(ref), self.eventViewCallback, self.openSingleServiceEPG, self.openMultiServiceEPG, self.openSimilarList)
        else:
            ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
            self.getNowNext()
            epglist = self.epglist
            if not epglist:
                self.is_now_next = False
                epg = eEPGCache.getInstance()
                ptr = ref and ref.valid() and epg.lookupEventTime(ref, -1)
                if ptr:
                    epglist.append(ptr)
                    ptr = epg.lookupEventTime(ref, ptr.getBeginTime(), +1)
                    if ptr:
                        epglist.append(ptr)
            else:
                self.is_now_next = True
            if epglist:
                self.eventView = self.session.openWithCallback(self.closed, EventViewEPGSelect, epglist[0], ServiceReference(ref), self.eventViewCallback, self.openSingleServiceEPG, self.openMultiServiceEPG, self.openSimilarList)
                self.dlg_stack.append(self.eventView)
        if not epglist:
            print 'no epg for the service avail.. so we show multiepg instead of eventinfo'
            self.openMultiServiceEPG(False)

    def eventViewCallback(self, setEvent, setService, val):
        epglist = self.epglist
        if len(epglist) > 1:
            tmp = epglist[0]
            epglist[0] = epglist[1]
            epglist[1] = tmp
            setEvent(epglist[0])


class InfoBarRdsDecoder():

    def __init__(self):
        self.rds_display = self.session.instantiateDialog(RdsInfoDisplay)
        self.session.instantiateSummaryDialog(self.rds_display)
        self.rass_interactive = None
        self.__event_tracker = ServiceEventTracker(screen=self, eventmap={iPlayableService.evEnd: self.__serviceStopped,
         iPlayableService.evUpdatedRassSlidePic: self.RassSlidePicChanged})
        self['RdsActions'] = ActionMap(['InfobarRdsActions'], {'startRassInteractive': self.startRassInteractive}, -1)
        self['RdsActions'].setEnabled(False)
        self.onLayoutFinish.append(self.rds_display.show)
        self.rds_display.onRassInteractivePossibilityChanged.append(self.RassInteractivePossibilityChanged)

    def RassInteractivePossibilityChanged(self, state):
        self['RdsActions'].setEnabled(state)

    def RassSlidePicChanged(self):
        if not self.rass_interactive:
            service = self.session.nav.getCurrentService()
            decoder = service and service.rdsDecoder()
            if decoder:
                decoder.showRassSlidePicture()

    def __serviceStopped(self):
        if self.rass_interactive is not None:
            rass_interactive = self.rass_interactive
            self.rass_interactive = None
            rass_interactive.close()

    def startRassInteractive(self):
        self.rds_display.hide()
        self.rass_interactive = self.session.openWithCallback(self.RassInteractiveClosed, RassInteractive)

    def RassInteractiveClosed(self, *val):
        if self.rass_interactive is not None:
            self.rass_interactive = None
            self.RassSlidePicChanged()
        self.rds_display.show()


class InfoBarSeek():
    SEEK_STATE_PLAY = (0, 0, 0, '>')
    SEEK_STATE_PAUSE = (1, 0, 0, '||')
    SEEK_STATE_EOF = (1, 0, 0, 'END')

    def __init__(self, actionmap = 'InfobarSeekActions'):
        self.__event_tracker = ServiceEventTracker(screen=self, eventmap={iPlayableService.evSeekableStatusChanged: self.__seekableStatusChanged,
         iPlayableService.evStart: self.__serviceStarted,
         iPlayableService.evEOF: self.__evEOF,
         iPlayableService.evSOF: self.__evSOF})
        self.fast_winding_hint_message_showed = False

        class InfoBarSeekActionMap(HelpableActionMap):

            def __init__(self, screen, *args, **kwargs):
                HelpableActionMap.__init__(self, screen, *args, **kwargs)
                self.screen = screen

            def action(self, contexts, action):
                print 'action:', action
                if action[:5] == 'seek:':
                    time = int(action[5:])
                    self.screen.doSeekRelative(time * 90000)
                    return 1
                elif action[:8] == 'seekdef:':
                    key = int(action[8:])
                    time = (-config.seek.selfdefined_13.value,
                     False,
                     config.seek.selfdefined_13.value,
                     -config.seek.selfdefined_46.value,
                     False,
                     config.seek.selfdefined_46.value,
                     -config.seek.selfdefined_79.value,
                     False,
                     config.seek.selfdefined_79.value)[key - 1]
                    self.screen.doSeekRelative(time * 90000)
                    return 1
                else:
                    return HelpableActionMap.action(self, contexts, action)

        self['SeekActions'] = InfoBarSeekActionMap(self, actionmap, {'playpauseService': (self.playpauseService, _('Pauze/Continue playback')),
         'pauseService': (self.pauseService, _('Pause playback')),
         'unPauseService': (self.unPauseService, _('Continue playback')),
         'okButton': (self.okButton, _('Continue playback')),
         'seekFwd': (self.seekFwd, _('Seek forward')),
         'seekFwdManual': (self.seekFwdManual, _('Seek forward (enter time)')),
         'seekBack': (self.seekBack, _('Seek backward')),
         'seekBackManual': (self.seekBackManual, _('Seek backward (enter time)')),
         'jumpPreviousMark': (self.seekPreviousMark, _('Jump to previous marked position')),
         'jumpNextMark': (self.seekNextMark, _('Jump to next marked position'))}, prio=-1)
        self['SeekActions'].setEnabled(False)
        self.seekstate = self.SEEK_STATE_PLAY
        self.lastseekstate = self.SEEK_STATE_PLAY
        self.onPlayStateChanged = []
        self.lockedBecauseOfSkipping = False
        self.__seekableStatusChanged()

    def makeStateForward(self, n):
        return (0,
         n,
         0,
         '>> %dx' % n)

    def makeStateBackward(self, n):
        return (0,
         -n,
         0,
         '<< %dx' % n)

    def makeStateSlowMotion(self, n):
        return (0,
         0,
         n,
         '/%d' % n)

    def isStateForward(self, state):
        return state[1] > 1

    def isStateBackward(self, state):
        return state[1] < 0

    def isStateSlowMotion(self, state):
        return state[1] == 0 and state[2] > 1

    def getHigher(self, n, lst):
        for x in lst:
            if x > n:
                return x

        return False

    def getLower(self, n, lst):
        lst = lst[:]
        lst.reverse()
        for x in lst:
            if x < n:
                return x

        return False

    def showAfterSeek(self):
        if isinstance(self, InfoBarShowHide):
            if isStandardInfoBar(self) and self.timeshiftEnabled():
                for c in self.onPlayStateChanged:
                    c(self.seekstate)

            else:
                self.doShow()

    def up(self):
        pass

    def down(self):
        pass

    def getSeek(self):
        service = self.session.nav.getCurrentService()
        if service is None:
            return
        seek = service.seek()
        if seek is None or not seek.isCurrentlySeekable():
            return
        return seek

    def isSeekable(self):
        if self.getSeek() is None or isStandardInfoBar(self) and not self.timeshiftEnabled():
            return False
        return True

    def __seekableStatusChanged(self):
        if not self.isSeekable():
            self['SeekActions'].setEnabled(False)
            self.setSeekState(self.SEEK_STATE_PLAY)
        else:
            self['SeekActions'].setEnabled(True)

    def __serviceStarted(self):
        self.fast_winding_hint_message_showed = False
        self.setSeekState(self.SEEK_STATE_PLAY)
        self.__seekableStatusChanged()

    def setSeekState(self, state):
        service = self.session.nav.getCurrentService()
        if service is None:
            return False
        if not self.isSeekable():
            if state not in (self.SEEK_STATE_PLAY, self.SEEK_STATE_PAUSE):
                state = self.SEEK_STATE_PLAY
        pauseable = service.pause()
        if pauseable is None:
            print 'not pauseable.'
            state = self.SEEK_STATE_PLAY
        self.seekstate = state
        if pauseable is not None:
            if self.seekstate[0]:
                print 'resolved to PAUSE'
                pauseable.pause()
            elif self.seekstate[1]:
                if not pauseable.setFastForward(self.seekstate[1]):
                    print 'resolved to FAST FORWARD'
                else:
                    self.seekstate = self.SEEK_STATE_PLAY
                    print 'FAST FORWARD not possible: resolved to PLAY'
            elif self.seekstate[2]:
                if not pauseable.setSlowMotion(self.seekstate[2]):
                    print 'resolved to SLOW MOTION'
                else:
                    self.seekstate = self.SEEK_STATE_PAUSE
                    print 'SLOW MOTION not possible: resolved to PAUSE'
            else:
                print 'resolved to PLAY'
                pauseable.unpause()
        for c in self.onPlayStateChanged:
            c(self.seekstate)

        self.checkSkipShowHideLock()
        if hasattr(self, 'ScreenSaverTimerStart'):
            self.ScreenSaverTimerStart()
        return True

    def playpauseService(self):
        if self.seekstate != self.SEEK_STATE_PLAY:
            self.unPauseService()
        else:
            self.pauseService()

    def okButton(self):
        if self.seekstate == self.SEEK_STATE_PLAY:
            return 0
        if self.seekstate == self.SEEK_STATE_PAUSE:
            self.pauseService()
        else:
            self.unPauseService()

    def pauseService(self):
        if self.seekstate == self.SEEK_STATE_PAUSE:
            if config.seek.on_pause.value == 'play':
                self.unPauseService()
            elif config.seek.on_pause.value == 'step':
                self.doSeekRelative(1)
            elif config.seek.on_pause.value == 'last':
                self.setSeekState(self.lastseekstate)
                self.lastseekstate = self.SEEK_STATE_PLAY
        else:
            if self.seekstate != self.SEEK_STATE_EOF:
                self.lastseekstate = self.seekstate
            self.setSeekState(self.SEEK_STATE_PAUSE)

    def unPauseService(self):
        print 'unpause'
        if self.seekstate == self.SEEK_STATE_PLAY:
            return 0
        self.setSeekState(self.SEEK_STATE_PLAY)

    def doSeek(self, pts):
        seekable = self.getSeek()
        if seekable is None:
            return
        seekable.seekTo(pts)

    def doSeekRelative(self, pts):
        seekable = self.getSeek()
        if seekable is None:
            return
        prevstate = self.seekstate
        if self.seekstate == self.SEEK_STATE_EOF:
            if prevstate == self.SEEK_STATE_PAUSE:
                self.setSeekState(self.SEEK_STATE_PAUSE)
            else:
                self.setSeekState(self.SEEK_STATE_PLAY)
        seekable.seekRelative(pts < 0 and -1 or 1, abs(pts))
        if abs(pts) > 100 and config.usage.show_infobar_on_skip.value:
            self.showAfterSeek()

    def seekFwd(self):
        seek = self.getSeek()
        if seek and not seek.isCurrentlySeekable() & 2:
            if not self.fast_winding_hint_message_showed and seek.isCurrentlySeekable() & 1:
                self.session.open(MessageBox, _('No fast winding possible yet.. but you can use the number buttons to skip forward/backward!'), MessageBox.TYPE_INFO, timeout=10)
                self.fast_winding_hint_message_showed = True
                return
            return 0
        if self.seekstate == self.SEEK_STATE_PLAY:
            self.setSeekState(self.makeStateForward(int(config.seek.enter_forward.value)))
        elif self.seekstate == self.SEEK_STATE_PAUSE:
            if len(config.seek.speeds_slowmotion.value):
                self.setSeekState(self.makeStateSlowMotion(config.seek.speeds_slowmotion.value[-1]))
            else:
                self.setSeekState(self.makeStateForward(int(config.seek.enter_forward.value)))
        elif self.seekstate == self.SEEK_STATE_EOF:
            pass
        elif self.isStateForward(self.seekstate):
            speed = self.seekstate[1]
            if self.seekstate[2]:
                speed /= self.seekstate[2]
            speed = self.getHigher(speed, config.seek.speeds_forward.value) or config.seek.speeds_forward.value[-1]
            self.setSeekState(self.makeStateForward(speed))
        elif self.isStateBackward(self.seekstate):
            speed = -self.seekstate[1]
            if self.seekstate[2]:
                speed /= self.seekstate[2]
            speed = self.getLower(speed, config.seek.speeds_backward.value)
            if speed:
                self.setSeekState(self.makeStateBackward(speed))
            else:
                self.setSeekState(self.SEEK_STATE_PLAY)
        elif self.isStateSlowMotion(self.seekstate):
            speed = self.getLower(self.seekstate[2], config.seek.speeds_slowmotion.value) or config.seek.speeds_slowmotion.value[0]
            self.setSeekState(self.makeStateSlowMotion(speed))

    def seekBack(self):
        seek = self.getSeek()
        if seek and not seek.isCurrentlySeekable() & 2:
            if not self.fast_winding_hint_message_showed and seek.isCurrentlySeekable() & 1:
                self.session.open(MessageBox, _('No fast winding possible yet.. but you can use the number buttons to skip forward/backward!'), MessageBox.TYPE_INFO, timeout=10)
                self.fast_winding_hint_message_showed = True
                return
            return 0
        seekstate = self.seekstate
        if seekstate == self.SEEK_STATE_PLAY:
            self.setSeekState(self.makeStateBackward(int(config.seek.enter_backward.value)))
        elif seekstate == self.SEEK_STATE_EOF:
            self.setSeekState(self.makeStateBackward(int(config.seek.enter_backward.value)))
            self.doSeekRelative(-6)
        elif seekstate == self.SEEK_STATE_PAUSE:
            self.doSeekRelative(-1)
        elif self.isStateForward(seekstate):
            speed = seekstate[1]
            if seekstate[2]:
                speed /= seekstate[2]
            speed = self.getLower(speed, config.seek.speeds_forward.value)
            if speed:
                self.setSeekState(self.makeStateForward(speed))
            else:
                self.setSeekState(self.SEEK_STATE_PLAY)
        elif self.isStateBackward(seekstate):
            speed = -seekstate[1]
            if seekstate[2]:
                speed /= seekstate[2]
            speed = self.getHigher(speed, config.seek.speeds_backward.value) or config.seek.speeds_backward.value[-1]
            self.setSeekState(self.makeStateBackward(speed))
        elif self.isStateSlowMotion(seekstate):
            speed = self.getHigher(seekstate[2], config.seek.speeds_slowmotion.value)
            if speed:
                self.setSeekState(self.makeStateSlowMotion(speed))
            else:
                self.setSeekState(self.SEEK_STATE_PAUSE)

    def seekFwdManual(self):
        self.session.openWithCallback(self.fwdSeekTo, MinuteInput)

    def fwdSeekTo(self, minutes):
        print 'Seek', minutes, 'minutes forward'
        self.doSeekRelative(minutes * 60 * 90000)

    def seekBackManual(self):
        self.session.openWithCallback(self.rwdSeekTo, MinuteInput)

    def rwdSeekTo(self, minutes):
        print 'rwdSeekTo'
        self.doSeekRelative(-minutes * 60 * 90000)

    def checkSkipShowHideLock(self):
        wantlock = self.seekstate != self.SEEK_STATE_PLAY
        if config.usage.show_infobar_on_skip.value:
            if self.lockedBecauseOfSkipping and not wantlock:
                self.unlockShow()
                self.lockedBecauseOfSkipping = False
            if wantlock and not self.lockedBecauseOfSkipping:
                self.lockShow()
                self.lockedBecauseOfSkipping = True

    def calcRemainingTime(self):
        seekable = self.getSeek()
        if seekable is not None:
            len = seekable.getLength()
            try:
                tmp = self.cueGetEndCutPosition()
                if tmp:
                    len = (False, tmp)
            except:
                pass

            pos = seekable.getPlayPosition()
            speednom = self.seekstate[1] or 1
            speedden = self.seekstate[2] or 1
            if not len[0] and not pos[0]:
                if len[1] <= pos[1]:
                    return 0
                time = (len[1] - pos[1]) * speedden / (90 * speednom)
                return time
        return False

    def __evEOF(self):
        if self.seekstate == self.SEEK_STATE_EOF:
            return
        seekstate = self.seekstate
        if self.seekstate != self.SEEK_STATE_PAUSE:
            self.setSeekState(self.SEEK_STATE_EOF)
        if seekstate not in (self.SEEK_STATE_PLAY, self.SEEK_STATE_PAUSE):
            seekable = self.getSeek()
            if seekable is not None:
                seekable.seekTo(-1)
        if seekstate == self.SEEK_STATE_PLAY:
            self.doEofInternal(True)
        else:
            self.doEofInternal(False)

    def doEofInternal(self, playing):
        pass

    def __evSOF(self):
        self.setSeekState(self.SEEK_STATE_PLAY)
        self.doSeek(0)

    def seekPreviousMark(self):
        if isinstance(self, InfoBarCueSheetSupport):
            self.jumpPreviousMark()

    def seekNextMark(self):
        if isinstance(self, InfoBarCueSheetSupport):
            self.jumpNextMark()


from Screens.PVRState import PVRState, TimeshiftState

class InfoBarPVRState():

    def __init__(self, screen = PVRState, force_show = False):
        self.onPlayStateChanged.append(self.__playStateChanged)
        self.pvrStateDialog = self.session.instantiateDialog(screen)
        self.onShow.append(self._mayShow)
        self.onHide.append(self.pvrStateDialog.hide)
        self.force_show = force_show

    def _mayShow(self):
        if self.shown and self.seekstate != self.SEEK_STATE_PLAY:
            self.pvrStateDialog.show()

    def __playStateChanged(self, state):
        playstateString = state[3]
        self.pvrStateDialog['state'].setText(playstateString)
        if not config.usage.show_infobar_on_skip.value and self.seekstate == self.SEEK_STATE_PLAY and not self.force_show:
            self.pvrStateDialog.hide()
        else:
            self._mayShow()


class TimeshiftLive(Screen):

    def __init__(self, session):
        Screen.__init__(self, session)


class InfoBarTimeshiftState(InfoBarPVRState):

    def __init__(self):
        InfoBarPVRState.__init__(self, screen=TimeshiftState, force_show=True)
        self.timeshiftLiveScreen = self.session.instantiateDialog(TimeshiftLive)
        self.onHide.append(self.timeshiftLiveScreen.hide)
        self.secondInfoBarScreen and self.secondInfoBarScreen.onShow.append(self.timeshiftLiveScreen.hide)
        self.secondInfoBarScreenSimple and self.secondInfoBarScreenSimple.onShow.append(self.timeshiftLiveScreen.hide)
        self.timeshiftLiveScreen.hide()
        self.__hideTimer = eTimer()
        self.__hideTimer.callback.append(self.__hideTimeshiftState)
        self.onFirstExecBegin.append(self.pvrStateDialog.show)

    def _mayShow(self):
        if self.timeshiftEnabled():
            if self.secondInfoBarScreen and self.secondInfoBarScreen.shown:
                self.secondInfoBarScreen.hide()
            if self.secondInfoBar
