/** Bundled demo desks — tap one in Settings to switch the active client key.
 *
 * Keys are deterministic (provisioned server-side by `app/provision_desks.py`,
 * same values on any DB). The picker writes `clientKey` immediately — no Save
 * needed. DEMO SCOPE: these keys ship in the JS bundle; rotate before any
 * real deployment.
 */

export interface DeskBundle {
  name: string;
  label: string;
  blurb: string;
  key: string;
}

export const DESK_BUNDLES: DeskBundle[] = [
  {
    name: "newspaper-desk",
    label: "Newspaper desk",
    blurb: "Everything, every urgency (min: low)",
    key: "nn_desk0001_all-news-all-day",
  },
  {
    name: "radio-tv-desk",
    label: "Radio / TV desk",
    blurb: "Disaster · politics · sports — high urgency only",
    key: "nn_desk0002_breaking-high-urgency",
  },
  {
    name: "foreign-desk",
    label: "Foreign desk",
    blurb: "Politics · international (min: normal)",
    key: "nn_desk0003_politics-international",
  },
  {
    name: "market-desk",
    label: "Market desk",
    blurb: "Economy news (min: normal)",
    key: "nn_desk0004_economy-markets",
  },
];
