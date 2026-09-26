#!/usr/bin/env python3
"""Публикация дельты devlog.md в ветку updates.

Берёт два последних коммита, трогавших devlog.md, считает дельту секций
и коммитит файл updates/ГГГГ-ММ-ДД-<sha7>.md в ветку updates:

- новая секция      -> публикуется целиком (заголовок + тело);
- изменённая секция -> только добавленные строки тела;
- удалённая секция  -> строка `удалено: <заголовок>`.

Первый коммит devlog.md — базлайн: ничего не публикуется, exit 0.
Если дельта секций пуста (правка шапки/памятки) — тоже exit 0.

Только python3 stdlib: subprocess / os / sys / datetime.
"""

import os
import subprocess
import sys
from datetime import datetime, timezone

DEVLOG = "devlog.md"
UPDATES_DIR = "updates"
UPDATES_BRANCH = "updates"
BOT_NAME = "devlog-bot"
BOT_EMAIL = "devlog-bot@users.noreply.github.com"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def run(args, cwd=None, env=None, input_text=None):
    res = subprocess.run(args, cwd=cwd, env=env, input=input_text,
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(
            "команда провалилась: %s\nstdout: %s\nstderr: %s\n"
            % (" ".join(args), res.stdout, res.stderr))
        sys.exit(1)
    return res.stdout.strip()


def git(args, **kw):
    return run(["git"] + args, **kw)


def parse_sections(text):
    """devlog.md -> (порядок заголовков, {заголовок: [строки тела]}).

    Секция начинается строкой `## `. Шапка файла до первой секции
    в дельте не участвует.
    """
    order, sections, current, body = [], {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = body
            current = line.rstrip()
            order.append(current)
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        sections[current] = body
    return order, sections


def trim_tail(lines):
    """Срезает пустой хвост тела секции."""
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def added_lines(old, new):
    """Строки новой версии тела, которых не было в старой (порядок новой)."""
    remaining = list(old)
    added = []
    for line in new:
        if line in remaining:
            remaining.remove(line)
        else:
            added.append(line)
    return added


def main():
    root = git(["rev-parse", "--show-toplevel"])

    def g(*args, **kw):
        return git(list(args), cwd=root, **kw)

    # --- 1. Два последних коммита, трогавших devlog.md ----------------------
    shas = g("log", "--format=%H", "-n", "2", "--", DEVLOG).split()
    if len(shas) < 2:
        print("базлайн: предыдущего коммита с devlog.md нет — ничего не публикуем")
        return 0
    cur_sha, prev_sha = shas

    new_text = g("show", cur_sha + ":" + DEVLOG)
    old_text = g("show", prev_sha + ":" + DEVLOG)

    # --- 2. Дельта секций ---------------------------------------------------
    new_order, new_secs = parse_sections(new_text)
    old_order, old_secs = parse_sections(old_text)

    chunks = []
    for heading in new_order:
        body = trim_tail(list(new_secs[heading]))
        if heading not in old_secs:
            chunks.append([heading] + body)              # новая секция целиком
        else:
            added = added_lines(trim_tail(list(old_secs[heading])), body)
            if added:
                chunks.append([heading] + added)         # добавленные строки
    for heading in old_order:
        if heading not in new_secs:
            chunks.append(["удалено: " + heading])       # удалённая секция

    if not chunks:
        print("дельта секций пуста (правка вне секций) — нечего публиковать")
        return 0

    short = cur_sha[:7]
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = UPDATES_DIR + "/" + day + "-" + short + ".md"

    lines = ["# Дельта девлога — " + day + " (коммит " + short + ")", ""]
    for chunk in chunks:
        lines += chunk
        lines.append("")
    content = "\n".join(lines).rstrip() + "\n"

    # --- 3. Коммит в ветку updates (plumbing, рабочее дерево не трогаем) ----
    parent = None
    if g("ls-remote", "--heads", "origin", UPDATES_BRANCH):
        g("fetch", "--quiet", "origin",
          "refs/heads/" + UPDATES_BRANCH + ":refs/remotes/origin/" + UPDATES_BRANCH)
        parent = g("rev-parse", "--verify",
                   "refs/remotes/origin/" + UPDATES_BRANCH)

    index_path = os.path.join(root, ".git", "devlog-updates.index")
    if os.path.exists(index_path):
        os.remove(index_path)
    idx_env = dict(os.environ, GIT_INDEX_FILE=index_path)

    g("read-tree", parent if parent else EMPTY_TREE, env=idx_env)
    blob = run(["git", "hash-object", "-w", "--stdin"], cwd=root,
               input_text=content)
    g("update-index", "--add", "--cacheinfo",
      "100644," + blob + "," + path, env=idx_env)
    tree = g("write-tree", env=idx_env)

    ident = dict(os.environ)
    for key, val in (("GIT_AUTHOR_NAME", BOT_NAME),
                     ("GIT_AUTHOR_EMAIL", BOT_EMAIL),
                     ("GIT_COMMITTER_NAME", BOT_NAME),
                     ("GIT_COMMITTER_EMAIL", BOT_EMAIL)):
        ident.setdefault(key, val)
    commit_args = ["git", "commit-tree", tree, "-m",
                   "devlog: дельта " + day + " (" + short + ")"]
    if parent:
        commit_args += ["-p", parent]
    commit = run(commit_args, cwd=root, env=ident)

    g("push", "origin", commit + ":refs/heads/" + UPDATES_BRANCH)
    base = ("поверх " + parent[:7]) if parent else "первый коммит ветки"
    print("опубликовано: " + path + " в ветку " + UPDATES_BRANCH +
          " (коммит " + commit[:7] + ", " + base + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
