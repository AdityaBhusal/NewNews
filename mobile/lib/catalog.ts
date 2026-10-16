/**
 * Dice catalog for the Ingest tab + the 200-seed pool reference.
 *
 * Each entry carries the STUB-predicted outcome (deterministic: score starts
 * 0.55; +0.15 length≥200, +0.10 date, +0.10 known place, +0.05 source marker;
 * −0.20 clickbait, −0.15 ALL-CAPS, −0.10 !!!-density; confidence 0.5 base,
 * +0.2 length≥150, −0.25 length<50, +0.1 place/date). Routing: score ≥ 0.75
 * AND confidence ≥ 0.4 → auto-validated, else human review.
 * With Groq live the direction holds but exact numbers move.
 */

export interface CatalogEntry {
  title: string;
  body: string;
  expect: "auto" | "review";
  certainty: "high" | "medium" | "low";
}

const WIRE = (place: string, beat: string, detail: string, date: string): string =>
  `${place}, ${date} — ${beat} ${detail} Officials confirmed the development in a press release on Tuesday, according to the ministry.`;

export const CATALOG: CatalogEntry[] = [
  {
    title: "Cabinet approves Rs 200 million flood relief",
    body: WIRE(
      "Kathmandu",
      "The cabinet approved flood relief worth 200 million rupees for six districts, ministers said.",
      "Construction and distribution work begins next month across flood-hit settlements in Sindhupalchok and Bardiya, and the Home Ministry will publish beneficiary lists.",
      "17 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "NEPSE climbs 42 points on banking rally",
    body: WIRE(
      "Kathmandu",
      "The NEPSE index climbed 42 points on Tuesday as banking shares rallied on third-quarter earnings.",
      "Market turnover crossed 8.1 billion rupees in Kathmandu while brokers in Pokhara reported heavy retail buying, Nepal Stock Exchange data showed.",
      "17 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "Monsoon landslide blocks Araniko Highway",
    body: WIRE(
      "Banepa",
      "A monsoon landslide blocked the Araniko Highway near Banepa, stranding hundreds of vehicles.",
      "Police evacuated three settlements as a precaution and said crews from Kavrepalanchok need two days to clear the debris, officials reported.",
      "16 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "Parliament passes budget amid opposition protest",
    body: "The government announced a new budget plan amid opposition protests in parliament.",
    expect: "review",
    certainty: "medium",
  },
  {
    title: "Valley air quality worsens",
    body: "Air quality in the Kathmandu Valley worsened this week as brick kilns resumed firing.",
    expect: "review",
    certainty: "medium",
  },
  {
    title: "New bus park opens in Butwal",
    body: "A new bus park opened in Butwal on Monday with room for 300 vehicles.",
    expect: "review",
    certainty: "medium",
  },
  {
    title: "Gold price hits record",
    body: "Gold prices hit a new record in the Nepali market on Friday.",
    expect: "review",
    certainty: "medium",
  },
  {
    title: "Local festival",
    body: "Villagers danced at harvest.",
    expect: "review",
    certainty: "low",
  },
  { title: "Short update", body: "Rain in Pokhara.", expect: "review", certainty: "low" },
  { title: "Okay news", body: "The meeting ended well.", expect: "review", certainty: "low" },
  {
    title: "SHOCKING miracle cure",
    body: "Miracle cure! Click here, 100% guaranteed!!",
    expect: "review",
    certainty: "low",
  },
  {
    title: "VIRAL exposed video",
    body: "VIRAL exposed video! Click now!!",
    expect: "review",
    certainty: "low",
  },
  {
    title: "India–Nepal border talks resume",
    body: WIRE(
      "New Delhi",
      "India and Nepal resumed diplomatic talks on border infrastructure and trade facilitation.",
      "Officials from both sides met in New Delhi and agreed on a joint survey of disputed pillars before winter, according to the foreign ministry.",
      "15 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "National cricket team wins thriller",
    body: WIRE(
      "Kathmandu",
      "Nepal won a last-ball thriller against the visiting side at the TU Cricket Ground.",
      "Chasing 187 in the tournament final, the captain hit the winning runs as a record crowd celebrated in Kirtipur, coaches said after the match.",
      "14 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "Dengue cases rise in Chitwan",
    body: WIRE(
      "Chitwan",
      "Dengue cases rose sharply in Chitwan with 340 new patients admitted this week.",
      "The health ministry deployed rapid response teams to Bharatpur hospitals and urged residents to clear stagnant water, officials said.",
      "13 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "Police arrest smuggling ring",
    body: WIRE(
      "Birgunj",
      "Police arrested five members of a cross-border smuggling ring in Birgunj.",
      "Officers seized undeclared electronics worth 12 million rupees and said the accused will appear in court on Monday, police reported.",
      "12 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "Everest cleanup collects 8 tonnes",
    body: WIRE(
      "Solukhumbu",
      "The Everest cleanup campaign collected eight tonnes of waste from high camps.",
      "Climbers and sherpas from Solukhumbu joined the conservation drive, and the collected waste was flown to Lukla for recycling, organisers said.",
      "11 October 2026",
    ),
    expect: "auto",
    certainty: "high",
  },
  {
    title: "Kathmandu road budget",
    body: "Kathmandu Metropolitan City announced a Rs 250 million road budget across 14 wards on 12 March 2026, officials said, with construction starting next month and running through the monsoon in Banepa and Lalitpur.",
    expect: "auto",
    certainty: "high",
  },
  {
    title: "काठमाडौंमा सडक विस्तार",
    body: "काठमाडौं, १७ अक्टोबर २०२६ — महानगरपालिकाले १४ वडामा सडक विस्तारका लागि २५ करोड रुपैयाँ बजेट घोषणा गर्‍यो। अधिकारीहरूका अनुसार निर्माण अर्को महिना सुरु हुनेछ।",
    // Latin-biased lexicons: no date/place/source hits, so Nepali text maxes at
    // length bonus only — review/high is the honest stub prediction (Groq differs).
    expect: "review",
    certainty: "high",
  },
  {
    title: "Startup funding round",
    body: "A Kathmandu software startup raised seed funding for its digital payment application, founders announced on 10 October 2026, with plans to hire twenty engineers in Lalitpur.",
    expect: "auto",
    certainty: "high",
  },
];

export function randomEntry(): CatalogEntry {
  return CATALOG[Math.floor(Math.random() * CATALOG.length)];
}
