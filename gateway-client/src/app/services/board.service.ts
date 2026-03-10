import { Injectable } from '@angular/core';
import { Task, ColumnId, COLUMNS } from '../models/task.model';

const STORAGE_KEY = 'duckclaw_board_tasks';

export type TasksByColumn = Record<ColumnId, Task[]>;

@Injectable({ providedIn: 'root' })
export class BoardService {
  getColumns() {
    return COLUMNS;
  }

  getTasksByColumn(): TasksByColumn {
    const tasks = this.getTasks();
    const result: TasksByColumn = { todo: [], in_progress: [], done: [] };
    for (const col of COLUMNS) {
      result[col.id] = tasks
        .filter(t => t.columnId === col.id)
        .sort((a, b) => a.order - b.order);
    }
    return result;
  }

  getTasks(): Task[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : this.getDefaultTasks();
    } catch {
      return this.getDefaultTasks();
    }
  }

  private getDefaultTasks(): Task[] {
    return [
      { id: this.uid(), title: 'Revisar documentación', columnId: 'todo', order: 0, createdAt: Date.now() },
      { id: this.uid(), title: 'Integrar con API', columnId: 'in_progress', order: 0, createdAt: Date.now() },
      { id: this.uid(), title: 'Deploy a producción', columnId: 'done', order: 0, createdAt: Date.now() },
    ];
  }

  saveFromColumns(data: TasksByColumn): void {
    const tasks: Task[] = [];
    for (const col of COLUMNS) {
      data[col.id].forEach((t, i) => {
        tasks.push({ ...t, columnId: col.id, order: i });
      });
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
  }

  addTask(title: string, columnId: ColumnId = 'todo'): Task {
    const tasks = this.getTasks();
    const maxOrder = Math.max(-1, ...tasks.filter(t => t.columnId === columnId).map(t => t.order));
    const task: Task = {
      id: this.uid(),
      title,
      columnId,
      order: maxOrder + 1,
      createdAt: Date.now(),
    };
    tasks.push(task);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
    return task;
  }

  updateTask(id: string, updates: Partial<Task>): void {
    const tasks = this.getTasks().map(t =>
      t.id === id ? { ...t, ...updates } : t
    );
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tasks));
  }

  deleteTask(id: string): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(this.getTasks().filter(t => t.id !== id)));
  }

  private uid(): string {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
}
