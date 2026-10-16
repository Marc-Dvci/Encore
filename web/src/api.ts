export interface PersonCard {
  id: string;
  kind: "resident" | "carer";
  first_name: string;
  last_initial: string;
  birth_year: number;
  age: number;
  city: string;
  country: string;
  room: string | null;
  present: boolean;
  languages: string;
  favourites: string[];
  needs_input: number;
  last_reaction: { at: string; reaction: string; entity_name: string } | null;
  staff_note: string | null;
  guest: boolean;
}

export interface Home {
  name: string;
  town: string;
  coordinator: string;
  lounge_time: string;
  house_rules: [string, string][];
  max_film_minutes: number;
  residents: PersonCard[];
  carers: PersonCard[];
  present: number;
  relations: string[];
  countries: string[];
}

export interface Item {
  entity_id: string;
  name: string;
  type: string;
  year: number | null;
  age_then: number | null;
  image: string | null;
  affinity: number;
  era_weight: number;
  score: number;
  lanes: string[];
  because: string[];
  genres: string[];
  genre_tags: { tag_id: string; name: string }[];
  popularity: number;
  description: string | null;
  songs?: string[];
  duration?: number | null;
  country?: string | null;
  start_year?: number | null;
}

export interface Shelf {
  domain: string;
  label: string;
  window: [number, number];
  items: Item[];
  considered: number;
  outside_era: number;
  lanes: string[];
  errors: string[];
}

export interface Favourite {
  id: number;
  person_id: string;
  label: string;
  kind: string;
  entity_id: string | null;
  entity_name: string | null;
  status: string;
  source: string;
}

export interface FamilyItem {
  id: number;
  label: string;
  kind: string;
  status: string;
  source: string;
  entity_id: string | null;
  name: string;
  year: number | null;
  image: string | null;
  songs: string[];
  description: string | null;
}

export interface Place {
  entity_id: string;
  name: string;
  address: string | null;
  distance_km: number;
  dishes: string[];
  price_level: number | null;
  wheelchair: boolean;
  affinity: number;
  image: string | null;
  phone: string | null;
}

export interface Candidate {
  entity_id: string;
  name: string;
  year: number;
  image: string | null;
  duration: number | null;
  genres: string[];
  popularity: number;
  nominated_by: string[];
  songs?: string[];
  song?: string | null;
  per_resident: { id: string; name: string; rank_pct: number; era: number; pct: number; affinity: number }[];
  min_pct: number;
  least_served: string;
  mean_pct: number;
  mean_affinity: number;
}

export interface Profile {
  person: {
    id: string; kind: string; first_name: string; last_initial: string; birth_year: number; age: number; city: string;
    country: string; demonym: string; languages: string; room: string; present: number; family_note: string | null;
    care_note: string | null; guest: boolean;
  };
  favourites: Favourite[];
  avoid: { id: number; tag_id: string | null; entity_id: string | null; label: string; source: string }[];
  house_rules: [string, string][];
  family: FamilyItem[];
  era: { window: [number, number]; shelves: Record<string, Shelf> } | null;
  food: { tag: string | null; places: Place[] } | null;
  pending: (Favourite & { candidates: { entity_id: string; name: string; year: number | null; image: string | null; popularity: number; description: string | null }[] })[];
  history: { id: number; at: string; entity_name: string; entity_type: string; reaction: string; carer: string | null; note: string | null }[];
  errors: string[];
}

export interface Step {
  kind: "open" | "discover" | "film" | "common" | "food";
  title: string;
  item?: (Item & FamilyItem) | null;
  song?: string | null;
  why: string;
  shared?: { name: string; kind: string; score: number }[];
  place?: Place;
}

export interface Plan {
  id: string;
  resident: { id: string; first_name: string; birth_year: number; city: string; country: string; languages: string; age: number };
  carer: { id: string; first_name: string; birth_year: number; city: string; country: string; languages: string; age: number };
  steps: Step[];
  words: { opener: string; prompts: string[]; if_quiet: string; greeting: string };
  words_source: "model" | "template";
  window: [number, number];
  warnings: string[];
  reactions?: { entity_id: string; reaction: string; entity_name: string }[];
}

export interface Effect {
  reaction: string;
  label: string;
  item: string;
  change: string;
  suggest_tags?: { tag_id: string; name: string }[];
  shelf_in: { name: string; year: number; because: string[] }[];
  shelf_out: { name: string; year: number }[];
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** A random token this browser keeps, so the people a visitor adds stay visible to them only. */
export function visitorToken(): string {
  const make = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
  try {
    let t = localStorage.getItem("encore-visitor");
    if (!t) {
      t = make();
      localStorage.setItem("encore-visitor", t);
    }
    return t;
  } catch {
    const w = window as unknown as { __encoreVisitor?: string };
    return (w.__encoreVisitor ??= make());
  }
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "x-encore-visitor": visitorToken() };
  if (body) headers["content-type"] = "application/json";
  const r = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(data.error || data.detail || `Request failed (${r.status})`, r.status);
  return data as T;
}

export const api = {
  get: <T,>(url: string) => req<T>("GET", url),
  post: <T,>(url: string, body?: unknown) => req<T>("POST", url, body ?? {}),
  del: <T,>(url: string) => req<T>("DELETE", url),
};

export const REACTIONS: { key: string; label: string }[] = [
  { key: "lit_up", label: "Lit up" },
  { key: "sang_along", label: "Sang or moved" },
  { key: "no_response", label: "No response" },
  { key: "upset", label: "Seemed upset" },
];

export function spotifyUrl(artist: string, song?: string | null) {
  return `https://open.spotify.com/search/${encodeURIComponent([song, artist].filter(Boolean).join(" "))}`;
}

export function youtubeUrl(q: string) {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
}
