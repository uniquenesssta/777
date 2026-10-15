//! Folder-only Windows dialog. Selection never writes or publishes settings.
use quote_desktop::{DesktopError, Result};
use windows::{
    core::HSTRING,
    Win32::{
        Foundation::{ERROR_CANCELLED, HWND},
        System::Com::{
            CoCreateInstance, CoInitializeEx, CoTaskMemFree, CoUninitialize, CLSCTX_INPROC_SERVER,
            COINIT_APARTMENTTHREADED,
        },
        UI::Shell::{
            FileOpenDialog, IFileOpenDialog, IShellItem, SHCreateItemFromParsingName,
            FOS_FORCEFILESYSTEM, FOS_NOCHANGEDIR, FOS_PATHMUSTEXIST, FOS_PICKFOLDERS,
            SIGDN_FILESYSPATH,
        },
    },
};
fn unavailable(_: windows::core::Error) -> DesktopError {
    DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE")
}
pub fn pick(owner: isize, initial: &str) -> Result<Option<String>> {
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            .ok()
            .map_err(unavailable)?;
        let result = (|| {
            let dialog: IFileOpenDialog =
                CoCreateInstance(&FileOpenDialog, None, CLSCTX_INPROC_SERVER)
                    .map_err(unavailable)?;
            dialog
                .SetOptions(
                    dialog.GetOptions().map_err(unavailable)?
                        | FOS_PICKFOLDERS
                        | FOS_FORCEFILESYSTEM
                        | FOS_PATHMUSTEXIST
                        | FOS_NOCHANGEDIR,
                )
                .map_err(unavailable)?;
            dialog
                .SetTitle(&HSTRING::from("选择共享保存文件夹"))
                .map_err(unavailable)?;
            if !initial.is_empty() {
                if let Ok(item) =
                    SHCreateItemFromParsingName::<_, _, IShellItem>(&HSTRING::from(initial), None)
                {
                    let _ = dialog.SetFolder(&item);
                }
            }
            if let Err(error) = dialog.Show(Some(HWND(owner as *mut _))) {
                return if error.code() == ERROR_CANCELLED.to_hresult() {
                    Ok(None)
                } else {
                    Err(unavailable(error))
                };
            }
            let item = dialog.GetResult().map_err(unavailable)?;
            let raw = item
                .GetDisplayName(SIGDN_FILESYSPATH)
                .map_err(unavailable)?;
            let path = raw.to_string();
            CoTaskMemFree(Some(raw.0.cast()));
            let path = path.map_err(|_| DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE"))?;
            if !path.starts_with("\\\\")
                || path.starts_with("\\\\?\\")
                || path.starts_with("\\\\.\\")
            {
                return Err(DesktopError::new(422, "PUBLISHED_DIRECTORY_REQUIRES_UNC"));
            }
            Ok(Some(path))
        })();
        CoUninitialize();
        result
    }
}
