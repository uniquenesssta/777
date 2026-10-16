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
            FOS_FILEMUSTEXIST, FOS_FORCEFILESYSTEM, FOS_NOCHANGEDIR, FOS_PATHMUSTEXIST,
            FOS_PICKFOLDERS, SIGDN_FILESYSPATH,
        },
    },
};
fn unavailable(_: windows::core::Error) -> DesktopError {
    DesktopError::new(503, "DIRECTORY_DIALOG_UNAVAILABLE")
}
fn allowed_path(path: &str, local: bool) -> bool {
    if path.starts_with("\\\\?\\") || path.starts_with("\\\\.\\") {
        return false;
    }
    if local {
        std::path::Path::new(path).is_absolute() && !path.starts_with("\\\\")
    } else {
        path.starts_with("\\\\")
    }
}
pub fn pick(owner: isize, initial: &str, local: bool, file: bool) -> Result<Option<String>> {
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
                        | if file {
                            FOS_FILEMUSTEXIST
                        } else {
                            FOS_PICKFOLDERS
                        }
                        | FOS_FORCEFILESYSTEM
                        | FOS_PATHMUSTEXIST
                        | FOS_NOCHANGEDIR,
                )
                .map_err(unavailable)?;
            dialog
                .SetTitle(&HSTRING::from(if file {
                    "选择 .qbackup 恢复文件"
                } else if local {
                    "选择本机文件夹"
                } else {
                    "选择共享保存文件夹"
                }))
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
            if !allowed_path(&path, local) {
                return Err(DesktopError::new(
                    422,
                    if local {
                        "DEVELOPER_LOCAL_PATH_REQUIRED"
                    } else {
                        "PUBLISHED_DIRECTORY_REQUIRES_UNC"
                    },
                ));
            }
            Ok(Some(path))
        })();
        CoUninitialize();
        result
    }
}

#[cfg(test)]
mod tests {
    use super::allowed_path;
    #[test]
    fn developer_local_selection_does_not_relax_shared_business_directories() {
        assert!(allowed_path(r"D:\中文 账本", true));
        assert!(!allowed_path(r"D:\中文 账本", false));
        assert!(allowed_path(r"\\server\share\中文", false));
        assert!(!allowed_path(r"\\server\share\中文", true));
        for path in [
            r"relative\path",
            r"D:relative",
            r"\\?\D:\data",
            r"\\.\pipe\data",
        ] {
            assert!(!allowed_path(path, true));
        }
    }
}
