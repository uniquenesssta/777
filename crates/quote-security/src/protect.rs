use crate::{Error, Result};
pub fn protect(data: &[u8], encrypt: bool, auxiliary: bool) -> Result<Vec<u8>> {
    #[cfg(not(windows))]
    {
        let _ = encrypt;
        if auxiliary {
            return Ok(data.to_vec());
        }
        Err(Error::new(503, "LOCAL_SECRET_UNAVAILABLE"))
    }
    #[cfg(windows)]
    {
        let _ = auxiliary;
        use std::ffi::c_void;
        #[repr(C)]
        struct Blob {
            size: u32,
            data: *mut u8,
        }
        #[link(name = "crypt32")]
        unsafe extern "system" {
            fn CryptProtectData(
                a: *const Blob,
                b: *const u16,
                c: *const Blob,
                d: *mut c_void,
                e: *mut c_void,
                f: u32,
                g: *mut Blob,
            ) -> i32;
            fn CryptUnprotectData(
                a: *const Blob,
                b: *mut *mut u16,
                c: *const Blob,
                d: *mut c_void,
                e: *mut c_void,
                f: u32,
                g: *mut Blob,
            ) -> i32;
        }
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn LocalFree(p: *mut c_void) -> *mut c_void;
        }
        let input = Blob {
            size: data.len() as u32,
            data: data.as_ptr() as *mut u8,
        };
        let mut out = Blob {
            size: 0,
            data: std::ptr::null_mut(),
        };
        unsafe {
            let ok = if encrypt {
                CryptProtectData(
                    &input,
                    std::ptr::null(),
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    1,
                    &mut out,
                )
            } else {
                CryptUnprotectData(
                    &input,
                    std::ptr::null_mut(),
                    std::ptr::null(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    1,
                    &mut out,
                )
            };
            if ok == 0 {
                if !out.data.is_null() {
                    LocalFree(out.data.cast());
                }
                return Err(Error::new(503, "LOCAL_SECRET_UNAVAILABLE"));
            }
            let value = std::slice::from_raw_parts(out.data, out.size as usize).to_vec();
            LocalFree(out.data.cast());
            Ok(value)
        }
    }
}
