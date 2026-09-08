import { defineRailway, project, service } from "railway/iac";

// Last resort for a per-service CaC repo. Prefer one .railway file for the
// project and drop this if you later combine services into that file.
export const partial = "hermes-agent-template";

export default defineRailway(() => {
  const hermes_agent_template = service("hermes-agent-template", {
    start: "/usr/bin/tini -g -- /app/start.sh",
    healthcheck: "/health",
    healthcheckTimeout: 300,
    // dockerfilePath from CaC: "Dockerfile"
    // builder from CaC: "dockerfile"
  });
  return project("hermes-agent", {
    resources: [hermes_agent_template],
  });
});
