"""Directory publication relative to the shared configuration, without I/O.

The manager can access the share via a local drive while sales uses UNC. Relative
paths bind to each role's config.json parent, so a local E: path never becomes a
sales workstation's E: path. External Windows directories must use UNC.
"""
import ntpath
import posixpath


def path_module(path):
    return ntpath if ntpath.splitdrive(path)[0] or "\\" in path else posixpath


def resolve_directory(value, config_path, default, *, sales=False):
    module = path_module(config_path)
    parent = module.dirname(module.abspath(config_path))
    text = (value or default).strip()
    if not text or "\x00" in text:
        raise ValueError("目录不能为空或含控制字符")
    if module is ntpath:
        drive, tail = ntpath.splitdrive(text)
        if drive and not drive.startswith("\\\\") and not tail.startswith(("\\", "/")):
            raise ValueError("目录不能使用相对盘符路径")
        if not drive and text.startswith(("\\", "/")):
            raise ValueError("目录须为共享配置下的相对路径或完整UNC路径")
        if sales and drive and not drive.startswith("\\\\"):
            raise ValueError("母版目录仍为本机盘符；请在母版重新保存目录，外部目录使用UNC路径")
    if module.isabs(text):
        return module.normpath(text)
    result = module.normpath(module.join(parent, text))
    if module.commonpath((parent, result)) != parent:
        raise ValueError("相对目录不能越过共享配置所在文件夹")
    return result


def publish_directory(value, config_path, default):
    module = path_module(config_path)
    parent = module.dirname(module.abspath(config_path))
    resolved = resolve_directory(value, config_path, default)
    try:
        if module.normcase(module.commonpath((parent, resolved))) == module.normcase(parent):
            return module.relpath(resolved, parent)
    except ValueError:  # Different drives/shares.
        pass
    if module is ntpath and not resolved.startswith("\\\\"):
        raise ValueError("配置目录之外的位置须使用UNC共享路径，不能发布本机盘符给子版")
    return resolved
