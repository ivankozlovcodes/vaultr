// ob-sessions git tail: branch, ahead/behind and repo per space place (carried over from iv-spaces).
// One look at a time per place; local repos are watched (watchFolder); remote ones are looked at
// again on the fallback. Never throws: a machine that is away just leaves the place "unsure".

import { exec, watchFolder } from "herdr";

const base = (path) => String(path ?? "").replace(/\/+$/, "").split("/").pop();
export const FALLBACK = 60000;

export class Git {
  constructor() {
    this.info = {}; // where -> { name, branch, ahead, behind, repo, linked } | null (not a repo)
    this.checked = {}; // where -> ms of the last look
    this.unsure = new Set(); // wheres git couldn't answer for
    this.pending = new Set();
    this.refreshing = false;
    this.watching = new Set();
    this.at = {}; // space id -> where at the last look
    this.busy = {}; // pane -> busy at the last look
    this.ready = {}; // machine -> layout ready at the last look
  }

  // Places whose git could have changed (see iv-spaces `due`).
  due(now, sp, ps, machinesNow, active, skipMachine) {
    const at = {};
    for (const s of sp) at[s.id] = where(s, ps);
    const keys = new Set(Object.values(at).filter((k) => JSON.parse(k)[1]));
    const due = new Set([...keys].filter((k) => !(k in this.info) && !this.pending.has(k)));
    for (const [id, k] of Object.entries(at)) if (this.at[id] && this.at[id] !== k && keys.has(k)) due.add(k);
    this.at = at;
    const spaceOf = {};
    for (const s of sp) for (const t of s.tabs ?? []) spaceOf[t.id] = s;
    const busy = {};
    for (const p of ps) {
      if (!p.terminal || !spaceOf[p.tab]) continue;
      busy[p.pane] = p.status === "working" || !(p.program?.shell || p.program?.agent);
      if (this.busy[p.pane] && !busy[p.pane]) this.sameRepo(at[spaceOf[p.tab].id], keys).forEach((k) => due.add(k));
    }
    this.busy = busy;
    for (const m of machinesNow) {
      const ready = m.layout === "ready";
      if (ready && this.ready[m.name] === false) for (const k of keys) if (JSON.parse(k)[0] === m.name) due.add(k);
      this.ready[m.name] = ready;
    }
    if (active) {
      for (const k of keys) {
        const asks = this.info[k] || this.unsure.has(k);
        if (asks && !skipMachine(JSON.parse(k)[0]) && now - (this.checked[k] ?? 0) > FALLBACK) due.add(k);
      }
    }
    for (const k of [...due]) if (this.pending.has(k)) due.delete(k);
    return due;
  }

  sameRepo(key, keys) {
    const repo = this.info[key]?.repo;
    return [key, ...(repo ? [...keys].filter((k) => this.info[k]?.repo === repo) : [])];
  }

  refresh(keys, cx) {
    for (const k of keys) this.pending.add(k);
    if (this.refreshing) return;
    this.refreshing = true;
    cx.spawn(async (cx) => {
      try {
        while (this.pending.size) {
          const batch = [...this.pending];
          await Promise.all(batch.map((key) => this.check(key, cx)));
          for (const k of batch) this.pending.delete(k);
        }
        const used = new Set(Object.values(this.info).filter(Boolean).map((g) => JSON.parse(g.repo)).filter(([on]) => !on).map(([, repo]) => repo));
        for (const repo of this.watching) if (!used.has(repo)) this.watching.delete(repo);
      } catch (e) {
        console.log(`ob-sessions: git refresh failed: ${e}`);
        this.pending.clear();
      }
      this.refreshing = false;
      cx.notify();
    });
  }

  async check(key, cx) {
    const [on, cwd] = JSON.parse(key);
    this.checked[key] = Date.now();
    this.unsure.delete(key);
    try {
      const opts = { cwd, on, timeout: 15000 };
      const [r, common] = await Promise.all([
        exec("git", ["rev-parse", "--path-format=absolute", "--show-toplevel"], opts),
        exec("git", ["rev-parse", "--path-format=absolute", "--git-common-dir"], opts),
      ]);
      if (r.code !== 0 || common.code !== 0) {
        if (!/not a git repository/i.test(r.code !== 0 ? r.stderr : common.stderr)) this.unsure.add(key);
        this.info[key] = null;
        return;
      }
      const top = r.stdout.replace(/\n$/, ""), repo = common.stdout.replace(/\n$/, "");
      const [branch, counts] = await Promise.all([
        exec("git", ["symbolic-ref", "-q", "HEAD"], opts),
        exec("git", ["rev-list", "--left-right", "--count", "HEAD...@{upstream}"], opts),
      ]);
      const name = repo.endsWith("/.git") ? base(repo.slice(0, -5)) : base(repo).replace(/\.git$/, "");
      const [ahead, behind] = counts.code === 0 ? counts.stdout.trim().split(/\s+/).map(Number) : [0, 0];
      this.info[key] = {
        name, top,
        branch: branch.code === 0 ? branch.stdout.trim().replace(/^refs\/heads\//, "") : "(detached)",
        ahead: ahead || 0, behind: behind || 0, repo: JSON.stringify([on, repo]), linked: repo !== `${top}/.git`,
      };
      if (!on) this.watch(repo, cx);
    } catch {
      this.info[key] ??= null;
      this.unsure.add(key);
    }
  }

  watch(repo, cx) {
    if (this.watching.has(repo)) return;
    this.watching.add(repo);
    cx.spawn(async (cx) => {
      try {
        while (this.watching.has(repo)) {
          await watchFolder(repo);
          const mine = JSON.stringify([null, repo]);
          if (this.watching.has(repo)) this.refresh(Object.keys(this.info).filter((k) => this.info[k]?.repo === mine), cx);
        }
      } catch { this.watching.delete(repo); }
    });
  }

  of(space, ps) { return this.info[where(space, ps)] ?? null; }
}

// Where a space is now: [machine, its first terminal's live folder (else where it was made)].
export function where(s, ps) {
  const tabs = new Set((s.tabs ?? []).map((c) => c.id));
  const cwd = ps.find((p) => tabs.has(p.tab) && p.cwd)?.cwd || s.folder || "";
  return JSON.stringify([s.machine ?? null, cwd]);
}
