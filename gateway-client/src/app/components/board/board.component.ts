import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { CdkDragDrop, DragDropModule, moveItemInArray, transferArrayItem } from '@angular/cdk/drag-drop';
import { BoardService, TasksByColumn } from '../../services/board.service';
import { Task, ColumnId } from '../../models/task.model';

@Component({
  selector: 'app-board',
  standalone: true,
  imports: [CommonModule, FormsModule, DragDropModule],
  templateUrl: './board.component.html',
  styleUrl: './board.component.css',
})
export class BoardComponent {
  columns: { id: ColumnId; title: string }[] = [];
  tasksByColumn: TasksByColumn = { todo: [], in_progress: [], done: [] };
  editingId: string | null = null;
  newTaskTitle = '';
  newTaskColumn: ColumnId = 'todo';

  constructor(private boardService: BoardService) {
    this.columns = this.boardService.getColumns();
    this.loadTasks();
  }

  loadTasks(): void {
    this.tasksByColumn = this.boardService.getTasksByColumn();
  }

  drop(event: CdkDragDrop<Task[]>): void {
    if (event.previousContainer === event.container) {
      moveItemInArray(event.container.data, event.previousIndex, event.currentIndex);
    } else {
      transferArrayItem(
        event.previousContainer.data,
        event.container.data,
        event.previousIndex,
        event.currentIndex
      );
    }
    this.boardService.saveFromColumns(this.tasksByColumn);
  }

  addTask(): void {
    const title = this.newTaskTitle.trim();
    if (!title) return;
    this.boardService.addTask(title, this.newTaskColumn);
    this.newTaskTitle = '';
    this.loadTasks();
  }

  startEdit(task: Task): void {
    this.editingId = task.id;
  }

  saveEdit(task: Task, title: string): void {
    const t = title.trim();
    if (t) this.boardService.updateTask(task.id, { title: t });
    this.editingId = null;
    this.loadTasks();
  }

  cancelEdit(): void {
    this.editingId = null;
  }

  deleteTask(task: Task): void {
    this.boardService.deleteTask(task.id);
    this.loadTasks();
  }

}
