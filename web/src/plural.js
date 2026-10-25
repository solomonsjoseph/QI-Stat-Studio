// Counts written as plain English: "1 record", "2 records".
export const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`
