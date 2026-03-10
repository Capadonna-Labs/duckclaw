import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, firstValueFrom } from 'rxjs';
import { environment } from '../environments/environment';

export interface ChatRequest {
  message: string;
  session_id?: string;
  history?: { role: string; content: string }[];
  stream?: boolean;
}

export interface ChatResponse {
  response: string;
  session_id: string;
}

export interface HistoryResponse {
  worker_id: string;
  session_id: string;
  history: { role: string; content: string }[];
}

@Injectable({ providedIn: 'root' })
export class AgentService {
  private readonly baseUrl = environment.apiUrl;
  private readonly headers = new HttpHeaders({
    'Content-Type': 'application/json',
    'X-Tailscale-Auth-Key': environment.authKey,
  });

  constructor(private http: HttpClient) {}

  chat(workerId: string, message: string, sessionId = 'default', stream = false): Observable<ChatResponse> {
    const body: ChatRequest = {
      message,
      session_id: sessionId,
      stream,
    };
    return this.http.post<ChatResponse>(
      `${this.baseUrl}/api/v1/agent/${workerId}/chat`,
      body,
      { headers: this.headers }
    );
  }

  getHistory(workerId: string, sessionId: string, limit = 6): Observable<HistoryResponse> {
    return this.http.get<HistoryResponse>(
      `${this.baseUrl}/api/v1/agent/${workerId}/history`,
      {
        params: { session_id: sessionId, limit: limit.toString() },
        headers: this.headers,
      }
    );
  }

  health(): Observable<{ status: string }> {
    return this.http.get<{ status: string }>(`${this.baseUrl}/health`, {
      headers: this.headers,
    });
  }

  systemHealth(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(
      `${this.baseUrl}/api/v1/system/health`,
      { headers: this.headers }
    );
  }

  listWorkers(): Observable<{ workers: string[] }> {
    return this.http.get<{ workers: string[] }>(
      `${this.baseUrl}/api/v1/agent/workers`,
      { headers: this.headers }
    );
  }
}
