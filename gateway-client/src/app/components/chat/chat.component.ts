import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AgentService } from '../../services/agent.service';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './chat.component.html',
  styleUrl: './chat.component.css',
})
export class ChatComponent {
  message = '';
  messages: { role: 'user' | 'assistant'; content: string }[] = [];
  loading = false;
  error: string | null = null;
  workerId = 'finanz';
  sessionId = 'default';

  constructor(private agentService: AgentService) {}

  send(): void {
    const text = this.message.trim();
    if (!text || this.loading) return;

    this.messages.push({ role: 'user', content: text });
    this.message = '';
    this.loading = true;
    this.error = null;

    this.agentService.chat(this.workerId, text, this.sessionId, false).subscribe({
      next: (res) => {
        this.messages.push({ role: 'assistant', content: res.response });
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
