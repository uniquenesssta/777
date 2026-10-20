"""Bounded build failure summaries in the existing session log, never raw output."""
import re
import p07_diagnostics as diagnostics

_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
_STAGES = {'resources', 'compile', 'sign', 'installer', 'verify'}
_SENSITIVE = re.compile(r'password|secret|token|ticket|authorization|private[_ ]?key|signing[_ ]?key|bearer\s', re.I)
_ERROR = re.compile(r'^(?:error(?:\[[A-Z]\d+\])?:|Tauri desktop build configuration:|failed to (?:build|bundle)|Error\s|error TS\d+:|.*\berror (?:C|LNK)\d+:)', re.I)


class BuildDiagnostics:
    def __init__(self, package_id):
        self.package_id = package_id
        self.stage = 'prepare'
        self.entries = []
        self.omitted = 0
        self.code = None
        self.seen_stages = set()

    def feed(self, raw):
        line = _ANSI.sub('', raw).strip()
        if line.startswith('QUOTE777_BUILD_STAGE='):
            stage = line.split('=', 1)[1]
            if stage in _STAGES:
                self.stage = stage
                if stage not in self.seen_stages:
                    self.seen_stages.add(stage)
                    diagnostics.event('package.stage', package_id=self.package_id, stage=stage)
            return
        if re.fullmatch(r'[A-Z][A-Z0-9_]{4,100}', line):
            self.code = line
        if not (_ERROR.match(line) or re.fullmatch(r'[A-Z][A-Z0-9_]{4,100}(?:: \d+)?', line)
                or re.match(r"^thread '[^']+'(?: \(\d+\))? panicked at [^:]+:\d+:\d+:$", line)):
            return
        # Compiler source excerpts/command lines/env values are not collected.
        # Reject entire credential-bearing diagnostics, including URL userinfo.
        if len(line) > 4096 or _SENSITIVE.search(line) or re.search(r'https?://\S*[@?]', line):
            line = '[sensitive or oversized build diagnostic omitted]'
        line = line[:384]
        if line in self.entries:
            return
        if len(self.entries) < 8:
            self.entries.append(line)
        else:
            self.omitted += 1

    def finish(self, state):
        if self.entries or state == 'failed':
            diagnostics.event('package.build_diagnostics', package_id=self.package_id,
                              stage=self.stage, state=state, diagnostics=self.entries,
                              omitted=self.omitted)
