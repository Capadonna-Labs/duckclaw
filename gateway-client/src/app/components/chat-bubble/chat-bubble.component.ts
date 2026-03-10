import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AgentService } from '../../services/agent.service';
import { forkJoin } from 'rxjs';

type ChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  workerId?: string;
};

@Component({
  selector: 'app-chat-bubble',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat-bubble.component.html',
  styleUrl: './chat-bubble.component.css',
})
export class ChatBubbleComponent implements OnInit {
  open = false;
  message = '';
  messages: ChatMessage[] = [];
  loading = false;
  error: string | null = null;
  workers: string[] = [];
  selectedWorkers: string[] = [];
  groupMode = false;
  sessionId = 'bubble-' + Date.now();

  constructor(private agentService: AgentService) {}

  ngOnInit(): void {
    this.agentService.listWorkers().subscribe({
      next: (res) => {
        this.workers = res.workers || [];
        if (this.workers.length > 0 && this.selectedWorkers.length === 0) {
          this.selectedWorkers = [this.workers[0]];
        }
      },
      error: () => {
        this.workers = ['finanz', 'support', 'research_worker'];
        this.selectedWorkers = [this.workers[0]];
      },
    });
  }

  toggle(): void {
    this.open = !this.open;
    this.error = null;
  }

  toggleWorker(workerId: string): void {
    if (this.groupMode) {
      const idx = this.selectedWorkers.indexOf(workerId);
      if (idx >= 0) {
        this.selectedWorkers = this.selectedWorkers.filter((w) => w !== workerId);
      } else {
        this.selectedWorkers = [...this.selectedWorkers, workerId];
      }
    } else {
      this.selectedWorkers = [workerId];
    }
  }

  send(): void {
    const text = this.message.trim();
    if (!text || this.loading || this.selectedWorkers.length === 0) return;

    this.messages.push({ role: 'user', content: text });
    this.message = '';
    this.loading = true;
    this.error = null;

    const requests = this.selectedWorkers.map((workerId) =>
      this.agentService.chat(workerId, text, `${this.sessionId}-${workerId}`, false)
    );

    forkJoin(requests).subscribe({
      next: (responses) => {
        responses.forEach((res, i) => {
          const workerId = this.selectedWorkers[i];
          this.messages.push({
            role: 'assistant',
            content: res.response,
            workerId,
          });
        });
        this.loading = false;
      },
      error: (err) => {
        this.error = err?.error?.detail || err?.message || 'Error de conexión';
        this.loading = false;
      },
    });
  }

  clear(): void {
    this.messages = [];
    this.error = null;
  }
}
