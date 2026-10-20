/* AI disclosure: Codex wrote this reproducible draft/diagram builder. */
const fs = require('node:fs');
const path = require('node:path');
const { Document, Packer, Paragraph, TextRun, ImageRun, Header, PageNumber } = require('docx');
const sharp = require('sharp');
const dir = __dirname;
const c = JSON.parse(fs.readFileSync(path.join(dir, 'content.json'), 'utf8'));
const box = (x,y,w,h,title,lines) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="#f4f6fa" stroke="#1e2761" stroke-width="2"/><text x="${x+w/2}" y="${y+27}" text-anchor="middle" font-weight="bold" font-size="19">${title}</text>${lines.map((s,i)=>`<text x="${x+w/2}" y="${y+53+i*23}" text-anchor="middle" font-size="17">${s}</text>`).join('')}`;
const arrow = points => `<polyline points="${points}" fill="none" stroke="#1e2761" stroke-width="2.5" marker-end="url(#arrow)"/>`;
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="640" viewBox="0 0 1100 640"><defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0,0 L9,4.5 L0,9" fill="#1e2761"/></marker></defs><rect width="1100" height="640" fill="white"/><g font-family="Arial, sans-serif" fill="#17213a">
${box(360,10,380,65,'Scientific PDF',['Page images and native text'])}
${arrow('550,75 550,105')}
${box(250,105,600,100,'Front end, detection and molecule filter',['Peter | PeterAdr14','Crops, coordinates, text and table geometry'])}
${arrow('550,205 550,235')}
${box(350,235,400,95,'Recognition and consensus',['Bijay | ArkAngel101','SMILES candidates and disagreements'])}
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
${box(250,525,600,95,'Canonicalization, export and scoring',['Will proposes shared adapter; all owners review','SMILES with provenance; precision, recall and output counts'])}

</g></svg>`;

const p = text => new Paragraph({children:[new TextRun(text)], spacing:{after:130,line:276}});
const h = text => new Paragraph({text,heading:'Heading1',spacing:{before:180,after:120},keepNext:true});
async function main() {
  fs.writeFileSync(path.join(dir,'pipeline.svg'),svg);
  const png = await sharp(Buffer.from(svg)).resize(2200).png().toBuffer();
  fs.writeFileSync(path.join(dir,'pipeline.png'),png);
  const children = [
    new Paragraph({text:c.title,style:'Title',spacing:{after:100}}),
    new Paragraph({children:[new TextRun({text:c.subtitle,size:20})],spacing:{after:180}}),
    h('Pipeline architecture'), ...c.architecture.map(p),
    new Paragraph({text:'Figure 1',spacing:{before:120,after:60},keepNext:true}),
    new Paragraph({children:[new TextRun({text:'Proposed stages and owners',italics:true})],keepNext:true,spacing:{after:80}}),
    new Paragraph({children:[new ImageRun({type:'png',data:png,transformation:{width:624,height:363},altText:{title:'Proposed Phase 2 pipeline',description:'PDF pages and text flow through Peter’s detection, Bijay’s recognition, Jin’s linking and Will’s R-group assembly to shared export and scoring.',name:'Pipeline diagram'}})],spacing:{line:240,lineRule:'auto',after:100}}),
    new Paragraph({children:[new TextRun({text:'Note. Responsibilities are proposed, not yet confirmed. Linking uses both text/geometry and reader outputs; complete drawings bypass assembly.',size:20})],spacing:{after:100}}),
    new Paragraph({text:'Phase 2 implementation and integration',heading:'Heading1',pageBreakBefore:true,spacing:{after:150}}),
    ...c.plan.map(p),
    new Paragraph({text:'AI disclosure',heading:'Heading1',pageBreakBefore:true,spacing:{after:150}}),p(c.disclosure),
    h('References'),...c.references.map(text=>new Paragraph({children:[new TextRun(text)],indent:{left:360,hanging:360},spacing:{after:180,line:276}}))
  ];
  const doc = new Document({creator:'Will Daly',title:c.title,description:'XN 1.4 architecture and Phase 2 section draft',
    styles:{default:{document:{run:{font:'Times New Roman',size:24,color:'000000'}}},paragraphStyles:[
      {id:'Title',name:'Title',basedOn:'Normal',run:{font:'Times New Roman',size:32,bold:true,color:'000000'}},
      {id:'Heading1',name:'Heading 1',basedOn:'Normal',next:'Normal',run:{font:'Times New Roman',size:26,bold:true,color:'000000'}}]},
    sections:[{properties:{page:{size:{width:12240,height:15840},margin:{top:1440,bottom:1440,left:1440,right:1440}}},
      headers:{default:new Header({children:[new Paragraph({alignment:'right',children:[new TextRun({children:[PageNumber.CURRENT],size:20})]})]})},children}]});
  fs.writeFileSync(path.join(dir,'Daly_1_4_Phase2Sections.docx'),await Packer.toBuffer(doc));
}
main().catch(error=>{console.error(error);process.exit(1)});
