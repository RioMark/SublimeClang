"""
Copyright (c) 2011 Fredrik Ehnbom

This software is provided 'as-is', without any express or implied
warranty. In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it
freely, subject to the following restrictions:

   1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would be
   appreciated but is not required.

   2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.

   3. This notice may not be removed or altered from any source
   distribution.
"""
from clang import cindex
import sublime_plugin
from sublime import Region
import sublime
import re

def select(view, line, col):
    point = view.text_point(line-1, col-1)
    s = view.sel()
    s.clear()
    s.add(view.word(point))
    view.show_at_center(point)

translationUnits = {}
index = None
class SublimeClangAutoComplete(sublime_plugin.EventListener):
    def __init__(self):
        s = sublime.load_settings("clang.sublime-settings")
        s.clear_on_change("options")
        s.add_on_change("options", self.load_settings)
        self.load_settings(s)
        self.recompile_active = False
        self.auto_complete_active = False

    def load_settings(self, s = None):
        global translationUnits
        translationUnits.clear()
        if s == None:
            s = sublime.load_settings("clang.sublime-settings")
        self.popupDelay = s.get("popupDelay", 500)
        self.dont_complete_startswith = s.get("dont_complete_startswith", ['operator','~'])
        self.recompileDelay = s.get("recompileDelay", 1000)
        self.hide_clang_output = s.get("hide_output_when_empty", False)
        self.add_language_option = s.get("add_language_option", True)

    def parse_res(self, compRes, prefix):
        #print compRes.kind, compRes.string
        representation = ""
        insertion = ""
        returnType = ""
        start = False;
        placeHolderCount = 0
        for chunk in compRes.string:
            if chunk.isKindTypedText():
                start = True
                if not chunk.spelling.startswith(prefix):
                    return (False, None, None)
                for test in self.dont_complete_startswith:
                    if chunk.spelling.startswith(test):
                        return (False, None, None)
            if chunk.isKindResultType():
                returnType = chunk.spelling
            else:
                representation = "%s%s" % (representation, chunk.spelling)
            if start and not chunk.isKindInformative():
                if chunk.isKindPlaceHolder():
                    placeHolderCount = placeHolderCount + 1
                    insertion = "%s${%d:%s}" % (insertion, placeHolderCount, chunk.spelling)
                else: 
                    insertion = "%s%s" % (insertion, chunk.spelling)
        return (True, "%s - %s" % (representation, returnType), insertion)

    def get_translation_unit(self, filename):
        global translationUnits 
        global index
        if index == None:
            index = cindex.Index.create()
        tu = None
        if filename not in translationUnits:
            s = sublime.load_settings("clang.sublime-settings")
            opts = []
            if s.has("options"):
                opts = s.get("options")
            if self.add_language_option:
                opts.append("-x")
                opts.append(self.get_language(sublime.active_window().active_view()))
            opts.append(filename)
            tu = index.parse(None, opts)
            if tu != None:
                translationUnits[filename] = tu
        else:
            tu = translationUnits[filename]        
        return tu

    def get_language(self, view):
        caret = view.sel()[0].a
        language = re.search("(?<=source\.)[a-zA-Z0-9+#]+", view.scope_name(caret))
        if language == None:
            return False
        return language.group(0)

    def is_supported_language(self, view):
        language = self.get_language(view)
        if language != "c++" and language != "c":
            return False
        return True

    def on_query_completions(self, view, prefix, locations):
        if not self.is_supported_language(view):
            return []

        tu = self.get_translation_unit(view.file_name())
        if tu == None:
            return []
        row,col = view.rowcol(locations[0]-len(prefix)) # Getting strange results form clang if I don't remove prefix
        unsaved_files = []
        if view.is_dirty():
            unsaved_files.append((view.file_name(), str(view.substr(Region(0, 65536)))))
          
        res = tu.codeComplete(view.file_name(), row+1, col+1, unsaved_files, 3)
        ret = []
        if res != None:
            #for diag in res.diagnostics:
            #    print diag
            #lastRes = res.results[len(res.results)-1].string
            #if "CurrentParameter" in str(lastRes):
            #    for chunk in lastRes:
            #        if chunk.isKindCurrentParameter():
            #            return [(chunk.spelling, "${1:%s}" % chunk.spelling)]
            #    return []
            line = view.substr(Region(view.line(locations[0]).a, locations[0]))
            onlyMembers = line.endswith(".") or line.endswith("->")

            for compRes in res.results:
                if onlyMembers and (compRes.kind != cindex.CursorKind.CXX_METHOD and compRes.kind != cindex.CursorKind.FIELD_DECL):
                    continue
                add, representation, insertion = self.parse_res(compRes, prefix)
                if add:
                    #print compRes.kind, compRes.string
                    ret.append((representation, insertion))
        return sorted(ret)

    def complete(self):
        if self.auto_complete_active:
            self.auto_complete_active = False
            self.view.window().run_command("auto_complete")

    def recompile(self):
        view = self.view
        unsaved_files = [(view.file_name(), view.substr(Region(0, 65536)))]
        tu = self.get_translation_unit(view.file_name())
        tu.reparse(unsaved_files)
        errString = ""
        show = False
        if len(tu.diagnostics):
            errString = ""
            for diag in tu.diagnostics:
                f = diag.location
                filename = "" 
                if f.file != None:
                    filename = f.file.name

                err = "%s:%d,%d - %s - %s" % (filename, f.line, f.column, diag.severityName, diag.spelling)
                errString = "%s%s\n" % (errString, err)
            show = True
        v = view.window().get_output_panel("clang")
        v.set_read_only(False)
        v.set_scratch(True)
        v.set_name("sublimeclang.%s" % view.file_name())
        e = v.begin_edit()
        v.insert(e, 0, errString)
        v.end_edit(e)
        v.set_read_only(True)
        if show:
            view.window().run_command("show_panel", {"panel": "output.clang"})
        elif self.hide_clang_output:
            view.window().run_command("hide_panel", {"panel": "output.clang"})
        self.recompile_active = False

    class callback:
        def __init__(self, line, col):
            self.line = line
            self.col = col
            sublime_plugin.all_callbacks['on_load'].append(self)

        def on_load(self, view):
            select(view, self.line, self.col)
            sublime_plugin.all_callbacks['on_load'].remove(self)

    def on_selection_modified(self, view):
        if view.name().startswith("sublimeclang"):
            inputFile = view.name()[13:]
            tu = self.get_translation_unit(inputFile)
            line,col = view.rowcol(view.sel()[0].a)
            if line >= len(tu.diagnostics):
                return
            loc = tu.diagnostics[line].location
            if loc.file != None:
                v = sublime.active_window().open_file(loc.file.name)
                if v.is_loading():
                    self.callback(loc.line,loc.column)
                else:
                    select(v,loc.line, loc.column)


    def on_modified(self, view):
        if (self.popupDelay <= 0 and self.reparseDelay <= 0) or not self.is_supported_language(view):
            return

        if self.recompileDelay > 0 and not self.recompile_active:
            self.recompile_active = True
            self.view = view
            sublime.set_timeout(self.recompile, self.recompileDelay)

        if self.popupDelay > 0:
            self.auto_complete_active = False
            caret = view.sel()[0].a
            word = view.substr(Region(view.word(caret).a, caret))
            if (word.endswith(".") or word.endswith("->") or word.endswith("::")):
                self.auto_complete_active = True
                self.view = view
                sublime.set_timeout(self.complete, self.popupDelay) 
