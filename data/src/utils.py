def pretty_size(size: int) -> str:
    if size < 1024:
        return f'{size} bytes'
    elif size < 1024 * 1024:
        return f'{size / 1024:.2f} KB'
    else:
        return f'{size / (1024 * 1024):.2f} MB'
