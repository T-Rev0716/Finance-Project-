// Railway Infrastructure as Code for the AdvisorLens backend (service
// `advisorlens-api` in project `advisorlens-demo`). It replaces the deprecated
// repo-root railway.json, which Railway stops reading on 2026-12-01.
//
// It carries exactly the railway.json settings: Dockerfile build from
// backend/Dockerfile with the repo root as build context (no rootDirectory),
// healthcheck /health with a 100 s timeout, restart policy ON_FAILURE.
//
// Railway does not read this file during deploys; it takes effect only through
// `railway config apply` after `railway config migrate cutover`. See DEPLOY.md.
import { defineRailway, github, project, service, volume } from "railway/iac";
// This repository manages only its own resources in the environment. Other
// repositories export their own partial name.
// See https://docs.railway.com/infrastructure-as-code#multi-repo-projects
export const partial = "advisorlens-api";
export default defineRailway(() => {
  const advisorlensApi = service("advisorlens-api", {
    // Explicit: the SDK only defaults to "main", and this repo's GitHub default
    // branch is not main. Production deploys from main.
    source: github("T-Rev0716/Finance-Project-", { branch: "main" }),
    build: { builder: "DOCKERFILE", dockerfilePath: "backend/Dockerfile" },
    healthcheck: "/health",
    healthcheckTimeout: 100,
    deploy: { restartPolicyType: "ON_FAILURE" },
    // Not a new volume: this keeps the existing /data volume (the SQLite
    // database) attached. Without it, `railway config plan` shows a
    // destructive detach. region/sizeMB must match the live volume, or plan
    // proposes changing them; update them here if the volume is resized.
    volumeMounts: { "/data": volume("advisorlens-api-volume", { region: "sfo", sizeMB: 500 }) },
  });

  return project("advisorlens-demo", {
    // Service variables (secrets included) stay managed on Railway, untouched.
    variables: { managed: false },
    resources: [advisorlensApi],
  });
});
