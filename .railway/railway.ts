import { defineRailway, project, service } from "railway/iac";

export const partial = "hermes-agent-all-in-one";

export default defineRailway(() => {
  const hermes_agent_all_in_one = service("hermes-agent-all-in-one", {
    healthcheck: "/api/status",
    healthcheckTimeout: 300,
    // dockerfilePath from CaC: "Dockerfile"
    // builder from CaC: "dockerfile"
  });
  return project("hermes-agent-all-in-one", {
    resources: [hermes_agent_all_in_one],
  });
});
