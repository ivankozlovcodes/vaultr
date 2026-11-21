// feedback_capture.js: captures the live window screenshot, UI tree, and diagnostics
// into ${appHome()}/data/ob-feedback/ before opening the ob-feedback dialog.
import * as fs from "fs/promises";
import {
  agents, appHome, exec, focused, home, keys, layout, layouts, machines, panes,
  readTextFile, settings, shared, spaces, terminals, updates, window as appWindow,
  writeTextFile,
} from "herdr";
import { provider } from "./kit.js";
import { runFeedbackCapture } from "./feedback_bundle.js";

export function captureFeedbackState(overrides = {}) {
  return runFeedbackCapture({
    appHome,
    home,
    layout,
    layouts,
    focused,
    spaces,
    panes,
    agents,
    terminals,
    machines,
    window: appWindow,
    settings,
    updates,
    keys,
    shared,
    provider,
    exec,
    readTextFile,
    writeTextFile,
    fs,
    ...overrides,
  });
}
