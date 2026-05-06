import type { Probot } from "probot";
import { handlePR } from "./bot.js";
import { log, logError } from "./utils.js";

export default function app(probot: Probot): void {
  log("VisualBot probot app booted");

  probot.on(["pull_request.opened", "pull_request.synchronize"], async (context) => {
    try {
      await handlePR(context);
    } catch (err) {
      logError("unhandled error in PR handler:", err);
    }
  });
}
