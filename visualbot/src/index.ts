import type { Probot } from "probot";
import { handlePR } from "./bot.js";
import { log, logError } from "./utils.js";
import {
  installLogPath,
  recordInstall,
  recordUninstall,
  recordReposAdded,
  recordReposRemoved,
} from "./install-log.js";

export default function app(probot: Probot): void {
  log("VisualBot probot app booted");
  log(`install events logging to ${installLogPath()}`);

  probot.on(["pull_request.opened", "pull_request.synchronize"], async (context) => {
    try {
      await handlePR(context);
    } catch (err) {
      logError("unhandled error in PR handler:", err);
    }
  });

  // Installation lifecycle. These are the only record of churn — an uninstall
  // leaves no trace in the API afterwards — so each handler swallows its own
  // errors: a telemetry failure must never 500 the webhook and trigger a
  // GitHub redelivery.
  probot.on("installation.created", async (context) => {
    try {
      recordInstall(context.payload);
    } catch (err) {
      logError("failed to record installation.created:", err);
    }
  });

  probot.on("installation.deleted", async (context) => {
    try {
      recordUninstall(context.payload);
    } catch (err) {
      logError("failed to record installation.deleted:", err);
    }
  });

  probot.on("installation_repositories.added", async (context) => {
    try {
      recordReposAdded(context.payload);
    } catch (err) {
      logError("failed to record installation_repositories.added:", err);
    }
  });

  probot.on("installation_repositories.removed", async (context) => {
    try {
      recordReposRemoved(context.payload);
    } catch (err) {
      logError("failed to record installation_repositories.removed:", err);
    }
  });
}
