# Voiceover: Sift on Akamai Cloud (3:37)

Read each block when its caption appears on screen. The bold label is the caption's
small heading, so follow the captions rather than a stopwatch. Times are approximate,
checked against frames of the final video. Each line is written to fit its window at
an easy pace.

---

**0:00 Title card**
> This is Sift, running live on Akamai Cloud. It turns a school kitchen's inventory into a recall pull sheet.

**0:08 THE PROBLEM**
> When a food recall lands, a kitchen has twenty-four hours to warn its distributor. Today, that's done by hand.

**0:15 BEFORE ANY DATA**
> With nothing uploaded, Sift doesn't say "all clear." It says it hasn't seen any inventory.

**0:22 INPUT**
> The kitchen uploads the export its software already makes.

**0:28 MATCHING**
> Each line is checked against a thousand recall records in Akamai's managed PostgreSQL. The file itself goes to Object Storage.

**0:38 RESULT**
> Forty-two items to pull, and both USDA deadlines are already counting down.

**0:48 THE PULL SHEET**
> The pull sheet shows what to pull, where it is, and why. The most serious recalls come first, grouped by cooler and freezer.

**1:06 EVIDENCE**
> Every line shows both records word for word, and the text that matched.

**1:13 THE SAFETY RULE**
> A line is PULL or HELD, and the database enforces it. Nothing clears itself. A person has to sign off.

**1:19 AKAMAI OBJECT STORAGE**
> This is the exact file that run read, from a private bucket, through a link that expires in an hour.

**1:31 NEXT MORNING**
> The next day's export adds one unbranded chickpea dip.

**1:39 AKAMAI INFERENCE**
> Sift holds anything it can't prove, so eight hundred twenty-seven lines are held. Which comes first?

**1:46 QWEN3-EMBEDDING-8B + PGVECTOR**
> Each held pair is embedded and ranked by meaning in one pgvector query. Then the Qwen model reads the closest thirty-six.

**1:54 THE RESULT**
> At the top: sliced turkey that matches a Class One recall, and the chickpea dip, a likely Sabra hummus. Its brand is missing.

**2:05 CHECKED, NEVER CLEARED**
> Each verdict quotes its reason. "Different" only moves a line down. It's still held.

**2:16 GEMMA VISION**
> In the walk-in, snap a case label.

**2:25 VISION MODEL READING**
> Gemma reads the product, firm, barcode and lot. The barcode is then looked up exactly.

**2:33 EXACT MATCH**
> It's a Class One recall, Sabra Classic Hummus, and the meaning check agrees.

**2:43 THE 24-HOUR CLOCK**
> Now the distributor notice, one email per distributor.

**2:47 DRAFTING**
> The model writes only the greeting and the sign-off.

**2:54 THE MODEL WRITES NO DATA**
> Every product, quantity, lot and recall number comes straight from the database. So does the request.

**3:01 CHECKED**
> And if the model's own words slip in a number, a code or an instruction, the email is flagged before anyone sends it.

**3:14 A PERSON SENDS IT**
> Sift drafts it. A person sends it.

**3:21 RUNNING ON AKAMAI CLOUD**
> All on Akamai: a Linode, managed PostgreSQL with pgvector, Object Storage, and three Akamai Inference models.

**3:29 Closing card**
> Sift. From the export a kitchen already has, to a pull sheet and a notice, with the evidence for every line attached.

---

## Recording the voice

- Play `demo/sift-akamai-demo.mp4` muted and record over it in any editor (Clipchamp on
  Windows works). Start each block when its caption heading appears.
- The video has no audio track, so your voice is the only sound.
- If a block runs long, let it spill into the next scroll shot. The scrolling stretches
  (0:48-1:05, 1:54-2:15, 3:01-3:13) have the most room.
