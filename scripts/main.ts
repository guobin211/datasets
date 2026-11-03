import { spawnSync } from 'node:child_process';
import { existsSync, statSync } from 'node:fs';
import { resolve } from 'node:path';

import { exportJsonlToCsv } from './utils.ts';

function parseManualArgs(rawArgs: string[]): {
  command: string;
  format: 'jsonl' | 'csv';
  forward: string[];
} {
  const forward: string[] = [];
  let command = 'help';
  let format: 'jsonl' | 'csv' = 'jsonl';

  for (let i = 0; i < rawArgs.length; i++) {
    const arg = rawArgs[i] ?? '';
    if (arg === '--help' || arg === '-h') {
      command = 'help';
      return { command, format, forward };
    }
    if (arg === '--format') {
      const value = rawArgs[i + 1] ?? '';
      if (value === 'csv' || value === 'jsonl') {
        format = value;
        i++;
        continue;
      }
      format = 'jsonl';
      continue;
    }
    if (arg === '--csv') {
      format = 'csv';
      continue;
    }
    if (!command || command === 'help') {
      command = arg;
    } else {
      forward.push(arg);
    }
  }

  return { command, format, forward };
}

function runCommand(command: string, args: string[]): number {
  const result = spawnSync(command, args, {
    stdio: 'inherit',
    shell: false,
  });

  if (result.error) {
    console.error(result.error.message);
    return 1;
  }

  return result.status ?? 0;
}

function toCsvOutputPath(outputPath: string): string {
  if (outputPath.toLowerCase().endsWith('.csv')) return outputPath;
  if (outputPath.toLowerCase().endsWith('.jsonl')) {
    return outputPath.slice(0, -'.jsonl'.length) + '.csv';
  }
  return `${outputPath}.csv`;
}

async function exportCsvIfNeeded(
  inputPath: string,
  outputPath: string,
  format: 'jsonl' | 'csv',
): Promise<void> {
  if (format !== 'csv') return;
  const resolvedInputPath = resolve(inputPath);
  if (!existsSync(resolvedInputPath)) {
    return;
  }
  if (statSync(resolvedInputPath).isDirectory()) {
    return;
  }

  const resolvedOutputPath = resolve(toCsvOutputPath(outputPath));
  await exportJsonlToCsv(resolvedInputPath, resolvedOutputPath);
}

function printHelp(): void {
  console.log(`Data pipeline entrypoint.

Usage:
  tsx scripts/main.ts <command> [options]

Commands:
  merge       merge-jsonl.ts wrapper
  categorize  cate-jsonl.ts / cate-other-jsonl.ts wrapper
  sample      dataset prepare wrapper (defaults to JSONL; --format csv exports CSV)
  help        show this help

Common options:
  --format jsonl|csv     output format (default: jsonl)
  --csv                 shorthand for --format csv
`);
}

async function main(): Promise<void> {
  const rawArgs = process.argv.slice(2);
  const { command, format, forward } = parseManualArgs(rawArgs);

  if (command === 'help' || rawArgs.length === 0) {
    printHelp();
    return;
  }

  if (command === 'merge') {
    const exitCode = runCommand(process.execPath, [
      '--import',
      'tsx',
      'scripts/merge-jsonl.ts',
      ...forward,
    ]);
    process.exit(exitCode);
  }

  if (command === 'categorize') {
    const exitCode = runCommand(process.execPath, [
      '--import',
      'tsx',
      'scripts/cate-jsonl.ts',
      ...forward,
    ]);
    if (exitCode !== 0) process.exit(exitCode);

    if (format === 'csv') {
      console.warn(
        'categorize writes one JSONL file per category; CSV export requires a single input file. Use --format csv with sample/export-csv instead.',
      );
    }
    return;
  }

  if (command === 'sample') {
    const cargoArgs = ['run', '--quiet', '--', 'dataset', 'prepare', ...forward];
    const exitCode = runCommand('cargo', cargoArgs);
    if (exitCode !== 0) process.exit(exitCode);

    const outputArgIndex = forward.findIndex((item) => item === '--out');
    const outputPath =
      outputArgIndex >= 0
        ? (forward[outputArgIndex + 1] ?? 'src-sampling/eval/sample.jsonl')
        : 'src-sampling/eval/sample.jsonl';

    await exportCsvIfNeeded(outputPath, outputPath, format);
    return;
  }

  console.error(`Unknown command: ${command}`);
  printHelp();
  process.exit(1);
}

await main();
