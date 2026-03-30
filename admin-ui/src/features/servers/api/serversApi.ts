import { apiGetJson } from "../../../shared/api/httpClient";

export type RuntimeServer = {
  id: number;
  name: string;
  enabled: boolean;
  protocol: string;
  host: string;
  port: number;
  active_clients: number;
  runtime: {
    health: string;
    xray_state: string;
    vpn_latency_text: string;
    established_connections?: number;
    error?: string;
  };
};

export type ServersRuntimeSnapshot = {
  generated_at: string;
  servers: RuntimeServer[];
};

export function getServersRuntime(): Promise<ServersRuntimeSnapshot> {
  return apiGetJson<ServersRuntimeSnapshot>("/servers/runtime-live");
}
