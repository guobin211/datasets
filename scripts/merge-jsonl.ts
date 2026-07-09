import { createWriteStream } from 'node:fs';
import { readdir } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { parseArgs } from 'node:util';

import { readJsonl } from './utils.ts';

/** 将单个 jsonl 文件的非空行写入输出流，返回写入行数。 */
async function mergeFile(
  path: string,
  out: ReturnType<typeof createWriteStream>,
): Promise<number> {
  let lines = 0;
  for await (const line of readJsonl(path)) {
    if (!out.write(line + '\n')) {
      await new Promise<void>((resolve) => {
        out.once('drain', () => resolve());
      });
    }
    lines++;
  }
  return lines;
}

/** 合并单个目录下的所有 .jsonl 文件到指定输出文件。 */
async function mergeSingleDir(srcDir: string, outPath: string): Promise<void> {
  const absOut = resolve(outPath);
  const entries = await readdir(srcDir, { withFileTypes: true });

  const files: string[] = [];
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    if (!entry.name.endsWith('.jsonl')) continue;
    const absPath = resolve(join(srcDir, entry.name));
    if (absPath === absOut) continue;
    files.push(absPath);
  }

  if (files.length === 0) {
    console.log(`跳过 ${srcDir}: 没有 .jsonl 文件`);
    return;
  }

  files.sort();

  const out = createWriteStream(absOut, { encoding: 'utf8' });
  let totalLines = 0;
  let totalFiles = 0;

  for (const file of files) {
    const lines = await mergeFile(file, out);
    totalLines += lines;
    totalFiles++;
    console.log(`  [${totalFiles}] ${file} => ${lines} 行`);
  }

  await new Promise<void>((resolve, reject) => {
    out.on('error', reject);
    out.end(() => resolve());
  });

  console.log(
    `${srcDir} => 合并完成: ${totalFiles} 个文件, ${totalLines} 行 -> ${absOut}`,
  );
}

/** 递归遍历 root 下所有子目录，每个目录生成 merge.jsonl。 */
async function mergeAllSubdirs(root: string): Promise<void> {
  const entries = await readdir(root, { withFileTypes: true });
  entries.sort((a, b) => a.name.localeCompare(b.name));

  await mergeSingleDir(root, join(root, 'merge.jsonl'));

  for (const entry of entries) {
    if (entry.isDirectory()) {
      await mergeAllSubdirs(join(root, entry.name));
    }
  }
}

function printUsage(): void {
  console.log(`Usage: tsx scripts/merge-jsonl.ts [options]

Options:
  --root <dir>   项目根目录；设置后会对每个子目录生成 merge.jsonl
  --dir <dir>    源目录，包含要合并的 .jsonl 文件 (默认 ".")
  --out <file>   合并后的输出文件路径 (默认 "merge.jsonl")
  -h, --help     显示帮助信息`);
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      root: { type: 'string', default: '' },
      dir: { type: 'string', default: '.' },
      out: { type: 'string', default: 'merge.jsonl' },
      help: { type: 'boolean', short: 'h' },
    },
    allowPositionals: false,
  });

  if (values.help) {
    printUsage();
    return;
  }

  const root = values.root ?? '';
  const srcDir = values.dir ?? '.';
  const out = values.out ?? 'merge.jsonl';

  try {
    if (root) {
      await mergeAllSubdirs(root);
      return;
    }
    await mergeSingleDir(srcDir, out);
  } catch (err) {
    console.error(
      `处理失败: ${err instanceof Error ? err.message : String(err)}`,
    );
    process.exit(1);
  }
}

await main();
