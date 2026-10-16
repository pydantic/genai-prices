---
pre-agent-steps:
  - name: Install the gh-aw fetch transport
    run: |
      npm install --ignore-scripts --no-save --package-lock=false --no-audit --no-fund --prefix "$RUNNER_TEMP/gh-aw/price-check-fetch" undici@6.28.0
      echo "NODE_PATH=$RUNNER_TEMP/gh-aw/price-check-fetch/node_modules${NODE_PATH:+:$NODE_PATH}" >> "$GITHUB_ENV"
  - name: Install the price-check scope preflight
    run: |
      uv run python - <<'PY'
      import json
      import os
      import shlex
      import shutil
      import subprocess
      from pathlib import Path
      from ruamel.yaml import YAML

      directory = Path(os.environ['RUNNER_TEMP']) / 'gh-aw/price-check-scope'
      directory.mkdir()
      workflow_file = os.environ['GITHUB_WORKFLOW_REF'].split('@', 1)[0].rsplit('/', 1)[1]
      source_file = Path('.github/workflows') / (workflow_file.removesuffix('.lock.yml') + '.md')
      if source_file.name not in {'agentic-price-check.md', 'agentic-model-price-check.md'}:
          raise ValueError('Unexpected price-check workflow')
      frontmatter = source_file.read_text().partition('\n---\n')[0].removeprefix('---\n')
      workflow = YAML(typ='safe').load(frontmatter)
      policy = directory / 'policy.json'
      policy.write_text(json.dumps({
          'base_sha': os.environ['GITHUB_SHA'],
          'allowed_files': workflow['safe-outputs']['create-pull-request']['allowed-files'],
          'helper_path': str(directory.parent / 'actions/manifest_file_helpers.cjs'),
      }))
      script = directory / 'check.cjs'
      shutil.copyfile('scripts/price_check_scope.cjs', script)
      hook = directory / 'pre-commit'
      hook.write_text('#!/bin/sh\nexec node ' + shlex.quote(str(script)) + ' ' + shlex.quote(str(policy)) + ' --staged\n')
      hook.chmod(0o755)
      subprocess.run(['git', 'config', 'core.hooksPath', str(directory)], check=True)
      with Path(os.environ['GITHUB_ENV']).open('a') as output:
          output.write(f'PRICE_CHECK_SCOPE_COMMAND=node {shlex.quote(str(script))} {shlex.quote(str(policy))}\n')
      PY
  - name: Snapshot trusted provider sources
    run: |
      mkdir -p "$RUNNER_TEMP/gh-aw/price-check"
      uv run python -m scripts.price_check_sources > "$RUNNER_TEMP/gh-aw/price-check/provider-sources.json"
---
