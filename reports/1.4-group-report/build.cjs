/* AI disclosure: Codex wrote the first version of this builder and the diagram; Claude extended it to the full group report. */
// Builds XNGroup1_1_4_GroupReport.docx and the pipeline diagram from:
//   front_content.json   title, members, literature review, disclosure, references
//   results_content.json results, analysis, conclusions, sponsor questions
//   results_tables.json  Tables 1-3 (run results_tables.py first)
//   phase2_content.json  pipeline architecture and Phase 2 plan
// Bracketed text ("[pending ...]") is a placeholder and is highlighted in the output.
// Run from the repo root:
//   NODE_PATH=<external-node_modules> node reports/1.4-group-report/build.cjs
const fs = require('node:fs');
const path = require('node:path');
const { Document, Packer, Paragraph, TextRun, ImageRun, Header, PageNumber, Table, TableRow, TableCell,
  WidthType, BorderStyle, AlignmentType } = require('docx');
const sharp = require('sharp');
const dir = __dirname;
const load = name => JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'));
const front = load('front_content.json'), res = load('results_content.json'), tables = load('results_tables.json'), ph = load('phase2_content.json');

const box = (x,y,w,h,title,lines) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="#f4f6fa" stroke="#1e2761" stroke-width="2"/><text x="${x+w/2}" y="${y+27}" text-anchor="middle" font-weight="bold" font-size="19">${title}</text>${lines.map((s,i)=>`<text x="${x+w/2}" y="${y+53+i*23}" text-anchor="middle" font-size="17">${s}</text>`).join('')}`;
const arrow = points => `<polyline points="${points}" fill="none" stroke="#1e2761" stroke-width="2.5" marker-end="url(#arrow)"/>`;
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="640" viewBox="0 0 1100 640"><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9" fill="#1e2761"/></marker></defs><rect width="1100" height="640" fill="white"/><g font-family="Arial, sans-serif" fill="#17213a">
${box(360,10,380,65,'Scientific PDF',['Page images and native text'])}
${arrow('550,75 550,105')}
${box(250,105,600,100,'Front end, detection and molecule filter',['Peter | PeterAdr14','Crops, coordinates, text and table geometry'])}
${arrow('550,205 550,235')}
${box(350,235,400,95,'Recognition and consensus',['Bijay | ArkAngel101','MolGlyph reads; MolScribe checks'])}
${arrow('350,282 210,282 210,365')}
${box(25,365,370,95,'Label and table linking',['Jin | liba-jin','Labels, scaffold links and row IDs'])}
${arrow('250,155 10,155 10,350 210,350 210,365')}
<text x="24" y="260" font-size="16">Text and geometry</text>
${arrow('395,412 440,412')}
${box(440,365,330,95,'R-group assembly',['Will | willdaly','Complete molecules or abstentions'])}
${arrow('605,460 605,495 550,495 550,525')}
${arrow('750,282 1010,282 1010,565 850,565')}
<text x="800" y="315" font-size="16">Complete drawings</text>
${arrow('210,460 210,565 250,565')}
<text x="25" y="510" font-size="16">Linked labels</text>
${box(250,525,600,95,'Canonicalization, export and scoring',['Will | willdaly','SMILES with provenance; precision, recall and output counts'])}

</g></svg>`;

// A string starting with "[" is a placeholder: highlight it so it cannot slip into the submission unnoticed.
const runs = text => text.split(/(\[[^\]]*\])/).filter(Boolean)
  .map(part => new TextRun({text:part, ...(part.startsWith('[') ? {highlight:'yellow'} : {})}));
const p = text => new Paragraph({children:runs(text), spacing:{after:130,line:276}});
const h = text => new Paragraph({text,heading:'Heading1',spacing:{before:180,after:120},keepNext:true});
const rule = {style:BorderStyle.SINGLE,size:4,color:'000000'};
const none = {style:BorderStyle.NONE,size:0,color:'FFFFFF'};

// APA-style table: rules above and below the header and at the bottom, no vertical lines.
function table(key, colWidths) {
  const meta = res.tables[key], rows = tables[key], total = colWidths.reduce((a, b) => a + b, 0);
  const cell = (text, r, i) => new TableCell({
    width:{size:colWidths[i],type:WidthType.DXA},
    margins:{top:30,bottom:30,left:60,right:60},
    borders:{top: r === 0 ? rule : none, bottom: r === 0 || r === rows.length - 1 ? rule : none, left:none, right:none},
    children:[new Paragraph({alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER, spacing:{line:240,lineRule:'auto'},
      children:[new TextRun({text:String(text), size:18, bold: r === 0})]})],
  });
  return [
    new Paragraph({children:[new TextRun({text:meta.label,bold:true})],spacing:{before:120,after:40},keepNext:true}),
    new Paragraph({children:[new TextRun({text:meta.caption,italics:true})],spacing:{after:80},keepNext:true}),
    new Table({width:{size:total,type:WidthType.DXA},columnWidths:colWidths,
      rows:rows.map((row, r) => new TableRow({cantSplit:true,tableHeader: r === 0, children:row.map((text, i) => cell(text, r, i))}))}),
    new Paragraph({children:[new TextRun({text:meta.note,size:20})],spacing:{before:60,after:160}}),
  ];
}

async function main() {
  fs.writeFileSync(path.join(dir,'pipeline.svg'),svg);
  const png = await sharp(Buffer.from(svg)).resize(2200).png().toBuffer();
  fs.writeFileSync(path.join(dir,'pipeline.png'),png);
  const children = [
    new Paragraph({text:front.title,style:'Title',spacing:{after:100}}),
    new Paragraph({children:[new TextRun({text:front.subtitle,size:20})],spacing:{after:60}}),
    new Paragraph({children:[new TextRun({text:front.repo,size:20})],spacing:{after:180}}),
    h('Team members and contributions'), p(front.members_intro),
    ...front.members.map(([name, did]) => new Paragraph({spacing:{after:80,line:276},indent:{left:360,hanging:360},
      children:[new TextRun({text:name,bold:true}), new TextRun(': '), ...runs(did)]})),
    h('Aggregated benchmark results'), ...res.results.map(p),
    ...table('recognition', [2500, 800, 1200, 1200, 1100, 1200, 1360]),
    ...table('older', [3000, 1800, 2280, 2280]),
    ...table('internal', [1480, 900, 2020, 1240, 1240, 1240, 1240]),
    h('Comparative analysis'), ...res.analysis.map(p),
    h('Group conclusions on tool performance'), ...res.conclusions.map(p),
    h('Questions for the sponsor'), p(res.questions_intro),
    ...res.questions.map(([q, body], i) => new Paragraph({spacing:{after:110,line:276},indent:{left:360,hanging:360},
      children:[new TextRun(`${i + 1}.\t`), new TextRun({text:q,bold:true}), new TextRun(body)]})),
    h('Group literature review'), p(front.lit_intro), ...front.lit.map(p),
    h('Pipeline architecture'), ...ph.architecture.map(p),
    new Paragraph({children:[new TextRun({text:'Figure 1',bold:true})],spacing:{before:120,after:40},keepNext:true}),
    new Paragraph({children:[new TextRun({text:'Pipeline stages and owners',italics:true})],keepNext:true,spacing:{after:80}}),
    new Paragraph({keepNext:true,children:[new ImageRun({type:'png',data:png,transformation:{width:624,height:363},altText:{title:'Phase 2 pipeline',description:'PDF pages and text flow through Peter’s detection, Bijay’s recognition, Jin’s linking and Will’s R-group assembly to shared export and scoring.',name:'Pipeline diagram'}})],spacing:{line:240,lineRule:'auto',after:100}}),
    new Paragraph({children:[new TextRun({text:'Note. Owners as assigned in issue 76. All stages run in one shared environment. Linking uses text, geometry and reader outputs; complete drawings bypass assembly.',size:20})],spacing:{after:100}}),
    h('Group approach to Phase 2'), ...ph.plan.map(p),
    h('AI disclosure'), p(front.disclosure),
    new Paragraph({text:'References',heading:'Heading1',pageBreakBefore:true,spacing:{after:150}}),
    ...front.references.map(text=>new Paragraph({children:[new TextRun(text)],indent:{left:360,hanging:360},spacing:{after:180,line:276}})),
  ];
  const doc = new Document({creator:'XN Project Group 1',title:front.title,description:'XN 1.4 group benchmark report and Phase 2 plan',
    styles:{default:{document:{run:{font:'Times New Roman',size:24,color:'000000'}}},paragraphStyles:[
      {id:'Title',name:'Title',basedOn:'Normal',run:{font:'Times New Roman',size:32,bold:true,color:'000000'}},
      {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',run:{font:'Times New Roman',size:26,bold:true,color:'000000'}}]},
    sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1440,bottom:1440,left:1440,right:1440}}},
      headers:{default:new Header({children:[new Paragraph({alignment:'right',children:[new TextRun({children:[PageNumber.CURRENT],size:20})]})]})},children}]});
  fs.writeFileSync(path.join(dir,'XNGroup1_1_4_GroupReport.docx'),await Packer.toBuffer(doc));
}
main().catch(error=>{console.error(error);process.exit(1)});
