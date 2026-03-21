import { chromium } from "playwright";
import { writeFileSync, mkdirSync } from "fs";
import { URL } from "url";

const BASE = "https://developer.tripletex.no";
const START = `${BASE}/docs/documentation/getting-started/`;
const DOCS_PREFIX = `${BASE}/docs/`;

const visited = new Set<string>();
const queue: string[] = [START];
const results: { url: string; title: string; content: string }[] = [];

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  while (queue.length > 0) {
    const url = queue.shift()!;
    const normalized = url.split("#")[0].replace(/\/$/, "");
    if (visited.has(normalized)) continue;
    visited.add(normalized);

    console.log(`[${visited.size}] Fetching: ${normalized}`);
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(1000); // extra wait for JS rendering

      const title = await page.title();
      const content = await page.evaluate(() => {
        // Try to get main content area
        const main =
          document.querySelector("article") ||
          document.querySelector(".entry-content") ||
          document.querySelector("main") ||
          document.querySelector("#content") ||
          document.body;
        return main?.innerText || "";
      });

      results.push({ url: normalized, title, content });

      // Collect all doc links
      const links = await page.evaluate((prefix: string) => {
        return Array.from(document.querySelectorAll("a[href]"))
          .map((a) => (a as HTMLAnchorElement).href)
          .filter((href) => href.startsWith(prefix));
      }, DOCS_PREFIX);

      for (const link of links) {
        const norm = link.split("#")[0].replace(/\/$/, "");
        if (!visited.has(norm)) {
          queue.push(link);
        }
      }
    } catch (e: any) {
      console.error(`  Error: ${e.message}`);
    }
  }

  await browser.close();

  // Save results
  const outDir = "/home/hendrik/Documents/agentic-avengers-nm-ai/hendrik/challenge1/tripletex-docs";
  mkdirSync(outDir, { recursive: true });

  // Save individual files
  for (const r of results) {
    const slug = new URL(r.url).pathname.replace(/^\/docs\//, "").replace(/\//g, "_").replace(/_$/, "") || "index";
    writeFileSync(`${outDir}/${slug}.txt`, `# ${r.title}\n# URL: ${r.url}\n\n${r.content}`);
  }

  // Save combined file
  const combined = results
    .map((r) => `${"=".repeat(80)}\n# ${r.title}\n# ${r.url}\n${"=".repeat(80)}\n\n${r.content}`)
    .join("\n\n");
  writeFileSync(`${outDir}/ALL_DOCS.txt`, combined);

  console.log(`\nDone! Scraped ${results.length} pages. Saved to ${outDir}/`);
}

main().catch(console.error);
