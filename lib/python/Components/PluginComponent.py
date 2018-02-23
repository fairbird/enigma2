from os import path as os_path, listdir as os_listdir
from bisect import insort
from Tools.Directories import fileExists, resolveFilename, SCOPE_PLUGINS
from Tools.Import import my_import
from Tools.Profile import profile
from Plugins.Plugin import PluginDescriptor
import keymapparser
from traceback import print_exc
from sys import stdout
from Components.Language import language
from Tools.Import import my_import

def languageChanged():
    plugins.clearPluginList()
    plugins.readPluginList(resolveFilename(SCOPE_PLUGINS))

class PluginComponent:
    firstRun = True
    restartRequired = False

    def __init__(self):
        self.plugins = {}
        self.pluginList = []
        self.installedPluginList = []
        self.setPluginPrefix('Plugins.')
        self.resetWarnings()

    def setPluginPrefix(self, prefix):
        self.prefix = prefix

    def addPlugin(self, plugin):
        if self.firstRun or not plugin.needsRestart:
            self.pluginList.append(plugin)
            for x in plugin.where:
                insort(self.plugins.setdefault(x, []), plugin)
                if x == PluginDescriptor.WHERE_AUTOSTART:
                    plugin(reason=0)

        else:
            self.restartRequired = True

    def removePlugin(self, plugin):
        self.pluginList.remove(plugin)
        for x in plugin.where:
            self.plugins[x].remove(plugin)
            if x == PluginDescriptor.WHERE_AUTOSTART:
                plugin(reason=1)

    def readPluginList(self, directory):
        categories = os_listdir(directory)
        new_plugins = []
        for c in categories:
            directory_category = directory + c
            if not os_path.isdir(directory_category):
                continue
            for pluginname in os_listdir(directory_category):
                path = directory_category + '/' + pluginname
                if os_path.isdir(path):
                    if fileExists(path + '/plugin.pyc') or fileExists(path + '/plugin.pyo') or fileExists(path + '/plugin.py') or fileExists(path + '/plugin.so'):
                        try:
                            plugin = my_import('.'.join(['Plugins',
                             c,
                             pluginname,
                             'plugin']))
                            if not plugin.__dict__.has_key('Plugins'):
                                print "Plugin %s doesn't have 'Plugin'-call." % pluginname
                                continue
                            plugins = plugin.Plugins(path=path)
                        except Exception as exc:
                            print 'Plugin ', c + '/' + pluginname, 'failed to load:', exc
                            print_exc(file=stdout)
                            print 'skipping plugin.'
                            self.warnings.append((c + '/' + pluginname, str(exc)))
                            continue

                        if not isinstance(plugins, list):
                            plugins = [plugins]
                        for p in plugins:
                            p.path = path
                            p.updateIcon(path)
                            new_plugins.append(p)

                        if fileExists(path + '/keymap.xml'):
                            try:
                                keymapparser.readKeymap(path + '/keymap.xml')
                            except Exception as exc:
                                print 'keymap for plugin %s/%s failed to load: ' % (c, pluginname), exc
                                self.warnings.append((c + '/' + pluginname, str(exc)))

        plugins_added = [ p for p in new_plugins if p not in self.pluginList ]
        plugins_removed = [ p for p in self.pluginList if not p.internal and p not in new_plugins ]
        for p in plugins_removed:
            for pa in plugins_added:
                if pa.path == p.path and pa.where == p.where:
                    pa.needsRestart = False

        for p in plugins_removed:
            self.removePlugin(p)

        for p in plugins_added:
            if self.firstRun or p.needsRestart is False:
                self.addPlugin(p)
            else:
                for installed_plugin in self.installedPluginList:
                    if installed_plugin.path == p.path:
                        if installed_plugin.where == p.where:
                            p.needsRestart = False

                self.addPlugin(p)

        if self.firstRun:
            self.firstRun = False
            self.installedPluginList = self.pluginList

    def getPlugins(self, where):
        if not isinstance(where, list):
            return self.plugins.get(where, [])
        res = []
        for x in where:
            for p in self.plugins.get(x, []):
                insort(res, p)

        return res

    def getPluginsForMenu(self, menuid):
        res = []
        for p in self.getPlugins(PluginDescriptor.WHERE_MENU):
            res += p(menuid)

        return res

    def getDescriptionForMenuEntryID(self, menuid, entryid):
        for p in self.getPlugins(PluginDescriptor.WHERE_MENU):
            if p(menuid) and isinstance(p(menuid), (list, tuple)):
                if p(menuid)[0][2] == entryid:
                    return p.description

    def clearPluginList(self):
        self.pluginList = []
        self.plugins = {}

    def reloadPlugins(self, dummy = False):
        self.clearPluginList()
        self.readPluginList(resolveFilename(SCOPE_PLUGINS))

    def shutdown(self):
        for p in self.pluginList[:]:
            self.removePlugin(p)

    def resetWarnings(self):
        self.warnings = []

    def getNextWakeupTime(self):
        wakeup = -1
        for p in self.pluginList:
            current = p.getWakeupTime()
            if current > -1 and (wakeup > current or wakeup == -1):
                wakeup = current

        return int(wakeup)


plugins = PluginComponent()
