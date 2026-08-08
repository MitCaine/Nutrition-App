export type CalendarState = {
  is_established: boolean;
  authoritative_time_zone: string | null;
  calendar_revision?: number;
  /** Current calendar date in the authoritative zone, when established. */
  today?: string | null;
};

export type CalendarImpactEntry = {
  id: string;
  logged_date: string;
  food_name_snapshot: string | null;
  meal_type: string | null;
  amount_quantity: string;
  amount_unit: string;
};

export type CalendarImpactPreview = {
  calendar_revision: number;
  current_time_zone: string;
  proposed_time_zone: string;
  current_today: string;
  proposed_today: string;
  today_changes: boolean;
  affected_entry_count: number;
  affected_dates: string[];
  affected_entries: CalendarImpactEntry[];
  preview_token: string;
};
