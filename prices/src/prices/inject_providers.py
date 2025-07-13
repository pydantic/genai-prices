from __future__ import annotations

import re

from .update import get_providers_yaml
from .utils import root_dir


def inject_providers():
    """Injects a list of providers into the README.md file."""
    readme_path = root_dir / 'README.md'
    readme_content = readme_path.read_text()
    text, count = re.subn(
        r'(\[comment\]: +<> +\(providers-start\)).+(\[comment\]: +<> +\(providers-end\))',
        providers_list,
        readme_content,
        flags=re.DOTALL,
    )
    assert count == 1, f'README.md contains {count} providers sections, expected 1'

    if text != readme_content:
        readme_path.write_text(text)
        print('README.md updated with providers list')
    else:
        print('README.md already up to date')


def providers_list(m: re.Match[str]):
    open_comment, close_comment = m.groups()
    providers_yml = get_providers_yaml()

    providers = sorted(list(providers_yml.values()), key=lambda x: x.provider.id)
    bullets = '\n'.join(
        f'* [{provider_yml.provider.name}](prices/providers/{provider_yml.path.name}) - {len(provider_yml.provider.models)} models'
        for provider_yml in providers
    )
    return f'{open_comment}\n\n{bullets}\n\n{close_comment}'
