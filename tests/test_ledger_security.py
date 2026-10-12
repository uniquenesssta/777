"""DACL policy and Win32 call boundaries; mocks do not prove native ACLs."""
import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from quote_ledger.paths import LedgerError
from quote_ledger.security import _replace_dacl, _verify_dacl_sddl

SID = 'S-1-5-21-111-222-333-1001'
ALLOWED = {SID, 'S-1-5-18', 'S-1-5-32-544'}
ENTRIES = f'(A;OICI;FA;;;{SID})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'


class LedgerSecurityTests(unittest.TestCase):
    def test_exact_principals_aliases_flags_order_and_equivalent_full_mask(self):
        for flags in ('P', 'PAI', 'PARAI', 'AIP'):
            with self.subTest(flags=flags):
                _verify_dacl_sddl('D:' + flags + ENTRIES, ALLOWED)
        _verify_dacl_sddl('D:P' + ENTRIES.replace('OICI;FA', 'CIOI;0x001f01ff'), ALLOWED)
        _verify_dacl_sddl('D:P' + ENTRIES.replace('SY', 'S-1-5-18').replace('BA', 'S-1-5-32-544'), ALLOWED)

    def test_extra_missing_duplicate_and_foreign_principals_are_rejected(self):
        for entries in (ENTRIES + '(A;OICI;FA;;;WD)', ENTRIES.replace('(A;OICI;FA;;;BA)', ''),
                        ENTRIES.replace('BA', 'SY'), ENTRIES.replace(SID, 'S-1-5-21-999-1001')):
            with self.subTest(entries=entries), self.assertRaises(LedgerError):
                _verify_dacl_sddl('D:P' + entries, ALLOWED)

    def test_denies_inherited_inherit_only_wrong_rights_and_object_aces_are_rejected(self):
        for changed in ('(D;OICI;FA;;;SY)', '(A;OICIID;FA;;;SY)', '(A;OICIIO;FA;;;SY)',
                        '(A;OI;FA;;;SY)', '(A;OIOI;FA;;;SY)', '(A;OICI;FR;;;SY)',
                        '(A;OICI;0x1fffff;;;SY)', '(A;OICI;FA;guid;;SY)'):
            with self.subTest(changed=changed), self.assertRaises(LedgerError):
                _verify_dacl_sddl('D:P' + ENTRIES.replace('(A;OICI;FA;;;SY)', changed), ALLOWED)

    def test_unprotected_null_empty_or_malformed_descriptors_are_rejected(self):
        for value in (None, '', 'D:', 'D:P', 'D:NO_ACCESS_CONTROL', 'D:AI' + ENTRIES,
                      'D:PX' + ENTRIES, 'D:P' + ENTRIES + 'S:', 'D:P' + ENTRIES + 'garbage'):
            with self.subTest(value=value), self.assertRaises(LedgerError):
                _verify_dacl_sddl(value, ALLOWED)

    def native_stub(self, *, write_error=0, null_dacl=False):
        api, free = Mock(), Mock()
        def convert(value, revision, descriptor, size):
            descriptor._obj.value = 1001
            return 1
        def get_dacl(descriptor, present, dacl, defaulted):
            present._obj.value = 1
            dacl._obj.value = None if null_dacl else 2002
            defaulted._obj.value = 0
            return 1
        api.ConvertStringSecurityDescriptorToSecurityDescriptorW.side_effect = convert
        api.GetSecurityDescriptorDacl.side_effect = get_dacl
        api.SetNamedSecurityInfoW.return_value = write_error
        return api, free

    def test_native_write_replaces_whole_dacl_sets_protected_flag_and_frees_after_write(self):
        api, free = self.native_stub()
        events = []
        api.SetNamedSecurityInfoW.side_effect = lambda *args: events.append('write') or 0
        free.side_effect = lambda pointer: events.append(('free', pointer.value))
        _replace_dacl('owned-directory', ALLOWED, api, free)
        expected = 'D:P' + ''.join(f'(A;OICI;FA;;;{sid})' for sid in sorted(ALLOWED))
        self.assertEqual(api.ConvertStringSecurityDescriptorToSecurityDescriptorW.call_args.args[:2], (expected, 1))
        args = api.SetNamedSecurityInfoW.call_args.args
        self.assertEqual(args[:5], ('owned-directory', 1, 0x80000004, None, None))
        self.assertEqual(args[5].value, 2002)
        self.assertIsNone(args[6])
        self.assertEqual(events, ['write', ('free', 1001)])

    def test_failed_native_write_raises_and_still_frees_descriptor(self):
        api, free = self.native_stub(write_error=5)
        with patch.object(ctypes, 'WinError', side_effect=lambda code: OSError(code, 'native denied'), create=True), self.assertRaises(OSError):
            _replace_dacl('owned-directory', ALLOWED, api, free)
        self.assertEqual(free.call_args.args[0].value, 1001)

    def test_null_dacl_never_reaches_native_write_and_allocation_is_freed(self):
        api, free = self.native_stub(null_dacl=True)
        with self.assertRaises(LedgerError):
            _replace_dacl('owned-directory', ALLOWED, api, free)
        api.SetNamedSecurityInfoW.assert_not_called()
        self.assertEqual(free.call_args.args[0].value, 1001)


if __name__ == '__main__':
    unittest.main()
