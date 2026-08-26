import { spawn } from 'node:child_process'
import { mkdtemp, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * @param {string} command
 * @param {readonly string[]} args
 * @param {string} cwd
 * @returns {Promise<void>}
 */
function run(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, stdio: 'inherit' })
    child.once('error', reject)
    child.once('close', (code) => {
      if (code === 0) {
        resolve()
      } else {
        reject(new Error(`${command} exited with code ${String(code ?? 'unknown')}`))
      }
    })
  })
}

async function main() {
  const packageDirectory = dirname(dirname(fileURLToPath(import.meta.url)))
  const temporaryDirectory = await mkdtemp(join(tmpdir(), 'genai-prices-packed-package-'))

  try {
    await run('npm', ['pack', '--pack-destination', temporaryDirectory], packageDirectory)
    const packedFiles = (await readdir(temporaryDirectory)).filter((file) => file.endsWith('.tgz'))
    if (packedFiles.length !== 1) {
      throw new Error(`Expected npm pack to produce one tarball, received ${String(packedFiles.length)}`)
    }

    const packedPackage = join(temporaryDirectory, packedFiles[0])
    await run('publint', ['run', '--strict', packedPackage], packageDirectory)
    await run('attw', ['--profile', 'strict', packedPackage], packageDirectory)
  } finally {
    await rm(temporaryDirectory, { force: true, recursive: true })
  }
}

/** @param {unknown} error */
function reportFailure(error) {
  console.error(error)
  process.exitCode = 1
}

main().catch(reportFailure)
