// Configured wards and beds used by the admission form. Occupancy is derived from
// active encounters; a bed held by an active encounter cannot be selected.
export const WARDS: { name: string; kind: string; beds: string[] }[] = [
  { name: "Ward 4", kind: "IPD", beds: ["4A", "4B", "4C", "4D"] },
  { name: "Ward 4B", kind: "IPD", beds: ["Bed 10", "Bed 11", "Bed 12", "Bed 13"] },
  { name: "Ward 5", kind: "IPD", beds: ["5A", "5B", "5C", "5D"] },
  { name: "ICU", kind: "ICU", beds: ["ICU-1", "ICU-2", "ICU-3", "ICU-4"] },
  { name: "Day Care", kind: "Day care", beds: ["DC-1", "DC-2", "DC-3", "DC-4"] },
];

export const ATTENDING = ["Dr. Meera Shah", "Dr. Arjun Rao", "Dr. Kavita Menon"];

export const bedKey = (ward: string, bed: string) => `${ward}::${bed}`;
