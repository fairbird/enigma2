import gettext
import os
from Tools.Directories import SCOPE_LANGUAGE, resolveFilename, fileExists
import language_cache
Translation = [['English', 'en', 'EN'],
 ['German', 'de', 'DE'],
 ['Arabic', 'ar', 'AE'],
 ['Brazilian Portuguese', 'pt_BR', 'BR'],
 ['Catalan', 'ca', 'AD'],
 ['Croatian', 'hr', 'HR'],
 ['Czech', 'cs', 'CZ'],
 ['Danish', 'da', 'DK'],
 ['Dutch', 'nl', 'NL'],
 ['Estonian', 'et', 'EE'],
 ['Finnish', 'fi', 'FI'],
 ['French', 'fr', 'FR'],
 ['Greek', 'el', 'GR'],
 ['Hebrew', 'he', 'IL'],
 ['Hungarian', 'hu', 'HU'],
 ['Lithuanian', 'lt', 'LT'],
 ['Latvian', 'lv', 'LV'],
 ['Icelandic', 'is', 'IS'],
 ['Italian', 'it', 'IT'],
 ['Norwegian', 'no', 'NO'],
 ['Persian', 'fa', 'IR'],
 ['Polish', 'pl', 'PL'],
 ['Portuguese', 'pt', 'PT'],
 ['Russian', 'ru', 'RU'],
 ['Serbian', 'sr', 'YU'],
 ['Slovakian', 'sk', 'SK'],
 ['Slovenian', 'sl', 'SI'],
 ['Spanish', 'es', 'ES'],
 ['Swedish', 'sv', 'SE'],
 ['Turkish', 'tr', 'TR'],
 ['Ukrainian', 'uk', 'UA'],
 ['Frisian', 'fy', 'x-FY']]

class Language:

    def __init__(self):
        self.currLangObj = gettext.install('enigma2', resolveFilename(SCOPE_LANGUAGE, ''), unicode=0, codeset='utf-8', names='ngettext')
        self.activeLanguage = 0
        self.lang = {}
        self.langlist = []
        list_dir = os.listdir('/usr/share/enigma2/po')
        print 'Installed_lang_dir:', list_dir
        for line in list_dir:
            for language in Translation:
                if line == language[1]:
                    self.addLanguage(_(language[0]), language[1], language[2])
                    break

        self.callbacks = []

    def addLanguage(self, name, lang, country):
        try:
            self.lang[str(lang + '_' + country)] = (_(name), lang, country)
            self.langlist.append(str(lang + '_' + country))
        except:
            print 'Language ' + str(name) + ' not found'

    def activateLanguage(self, index):
        try:
            if index not in self.lang:
                     print "Selected language %s does not exist, fallback to en_EN!" % index
                     index = "en_EN"
            lang = self.lang[index]
            print 'Activating language ' + lang[0]
            gettext._translations = {}
            self.currLangObj = gettext.translation('enigma2', resolveFilename(SCOPE_LANGUAGE, ''), languages=[lang[1]], fallback=True)
            self.currLangObj.install(names=('ngettext', 'pgettext'))
            os.environ['LANGUAGE'] = lang[1]
            self.activeLanguage = index
            self.activateLanguageFallback(index, 'enigma2-plugins')
            for x in self.callbacks:
                x()

        except:
            print "Error in activating language!"

    def activateLanguageFallback(self, index, domain):
        if index == self.getLanguage() and self.currLangObj:
            lang = self.lang[index]
            if fileExists(resolveFilename(SCOPE_LANGUAGE, lang[1] + '/LC_MESSAGES/' + domain + '.mo')):
                print 'Activating ' + domain + ' language fallback ' + lang[0]
                self.currLangObj.add_fallback(gettext.translation(domain, resolveFilename(SCOPE_LANGUAGE, ''), languages=[lang[1]], fallback=True))

    def activateLanguageIndex(self, index):
        if index < len(self.langlist):
            self.activateLanguage(self.langlist[index])

    def getLanguageList(self):
        return [ (x, self.lang[x]) for x in self.langlist ]

    def getActiveLanguage(self):
        return self.activeLanguage

    def getActiveLanguageIndex(self):
        idx = 0
        for x in self.langlist:
            if x == self.activeLanguage:
                return idx
            idx += 1

    def getLanguage(self):
        try:
            return str(self.lang[self.activeLanguage][1]) + '_' + str(self.lang[self.activeLanguage][2])
        except:
            return ''

    def addCallback(self, callback):
        self.callbacks.append(callback)

    def precalcLanguageList(self):
        T1 = _('Please use the UP and DOWN keys to select your language. Afterwards press the OK button.')
        T2 = _('Language selection')
        l = open('language_cache.py', 'w')
        print >> l, '# -*- coding: UTF-8 -*-'
        print >> l, 'LANG_TEXT = {'
        for language in self.langlist:
            self.activateLanguage(language)
            print >> l, '"%s": {' % language
            for name, lang, country in self.lang.values():
                print >> l, '\t"%s_%s": "%s",' % (lang, country, _(name))

            print >> l, '\t"T1": "%s",' % _(T1)
            print >> l, '\t"T2": "%s",' % _(T2)
            print >> l, '},'

        print >> l, '}'


language = Language()
