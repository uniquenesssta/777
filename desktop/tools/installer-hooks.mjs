// Windows installer lifecycle, separate from release build orchestration.
import { requireDelivery } from './deployment.mjs';

// Installed directory visibility only; preserve all existing attribute bits.
function hideHostDirectory() {
  return `Push $0
  Push $1
  System::Call 'kernel32::GetFileAttributesW(w "$INSTDIR\\host") i .r0'
  IntCmp $0 -1 quote777_host_visibility_failed
  IntOp $0 $0 | 0x6
  System::Call 'kernel32::SetFileAttributesW(w "$INSTDIR\\host", i r0) i .r1'
  IntCmp $1 0 quote777_host_visibility_failed
  Pop $1
  Pop $0
  Goto quote777_host_visibility_done
  quote777_host_visibility_failed:
    Pop $1
    Pop $0
    SetErrorLevel 5
    Abort "HOST_DIRECTORY_ATTRIBUTES_FAILED"
  quote777_host_visibility_done:`;
}

export function installerHooks(delivery) {
  requireDelivery(delivery);
  const other = delivery === 'manager' ? 'sales' : 'manager';
  return `!macro NSIS_HOOK_PREINSTALL
  IfFileExists "$INSTDIR\\quote777-${other}.exe" 0 +3
    SetErrorLevel 5
    Abort "DELIVERY_INSTALL_DIRECTORY_CONFLICT"
  ReadINIStr $0 "$INSTDIR\\quote777-install.ini" "release" "delivery"
  StrCmp $0 "" quote777_delivery_check_done
  StrCmp $0 "${delivery}" quote777_delivery_check_done
    SetErrorLevel 5
    Abort "DELIVERY_INSTALL_DIRECTORY_CONFLICT"
  quote777_delivery_check_done:
!macroend
!macro NSIS_HOOK_POSTINSTALL
  WriteINIStr "$INSTDIR\\quote777-install.ini" "release" "delivery" "${delivery}"
  ${delivery === 'manager' ? hideHostDirectory() : ''}
  ${delivery === 'manager' ? 'nsExec::ExecToStack \'"$SYSDIR\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\\host\\install.ps1" -Resources "$INSTDIR"\'\n  Pop $0\n  Pop $1' : ''}
!macroend
!macro NSIS_HOOK_POSTUNINSTALL
  Delete "$INSTDIR\\quote777-install.ini"
  RMDir "$INSTDIR"
!macroend
`;
}
