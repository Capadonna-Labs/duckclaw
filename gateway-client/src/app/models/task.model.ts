export type ColumnId = 'todo' | 'in_progress' | 'done';

export interface Task {
  id: string;
  title: string;
  description?: string;
  columnId: ColumnId;
  order: number;
  createdAt: number;
}

export interface Column {
  id: ColumnId;
  title: string;
}

export const COLUMNS: Column[] = [
  { id: 'todo', title: 'Por hacer' },
  { id: 'in_progress', title: 'En progreso' },
  { id: 'done', title: 'Hecho' },
];
