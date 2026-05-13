import { parseApiResponse } from "@/lib/http";

export interface SiteSessionData {
  graphs?: string[];
  roles?: string[];
  graph_roles?: Record<string, string[]>;
  [key: string]: unknown;
}

export function readSiteSession(): SiteSessionData {
  try {
    return JSON.parse(sessionStorage.getItem("site") || "{}");
  } catch {
    return {};
  }
}

export async function refreshSiteSession(): Promise<SiteSessionData> {
  const creds = sessionStorage.getItem("creds");
  const existing = readSiteSession();
  if (!creds) {
    return existing;
  }

  const response = await fetch("/ui/ui-login", {
    method: "POST",
    headers: {
      Authorization: `Basic ${creds}`,
    },
  });
  const data = await parseApiResponse(response);
  if (!response.ok) {
    throw new Error(
      data?.detail || `Failed to refresh site session: ${response.status}`
    );
  }
  const nextSite: SiteSessionData = {
    ...existing,
    ...data,
  };
  sessionStorage.setItem("site", JSON.stringify(nextSite));

  const availableGraphs = Array.isArray(nextSite.graphs) ? nextSite.graphs : [];
  const selectedGraph = sessionStorage.getItem("selectedGraph") || "";
  if (!selectedGraph || !availableGraphs.includes(selectedGraph)) {
    if (availableGraphs.length > 0) {
      sessionStorage.setItem("selectedGraph", availableGraphs[0]);
      window.dispatchEvent(new Event("graphrag:selectedGraph"));
    } else {
      sessionStorage.removeItem("selectedGraph");
      window.dispatchEvent(new Event("graphrag:selectedGraph"));
    }
  }

  return nextSite;
}
