import camelot
import pymupdf
import json
from pathlib import Path
import re

def extract_tables(path: str, opened_doc):
    tables = camelot.read_pdf(path, pages="1-15", flavor="auto")

    #use camelot filter to filter out bad detections, better, but still bad detections
    clean_tables = tables.filter(min_rows=2, min_columns=2).filter(min_accuracy=50)

    #save bounding boxes for each page
    table_data = {} #text of the tables

    for table in clean_tables:
        page_num = table.page
        page_height = opened_doc[page_num - 1].rect.height #indexing from 0
        bbox = table._bbox  #PDF coordinates

        converted_bbox = convert_camelot_bbox_to_pymupdf(bbox,page_height)

        #if there is no page record, add it
        if page_num not in table_data:
            table_data[page_num] = []

        #save table
        table_data[page_num].append({
            "bbox": converted_bbox,
            "content": table.df.to_dict(orient="records")
        })

    return table_data


def convert_camelot_bbox_to_pymupdf(bbox: tuple, page_height: float) -> tuple:
    """
        Convert Camelot coords (starting from top left) to pymupdf (bottom left) for the visualization to be correct.
    """
    x0, y0, x1, y1 = bbox
    return (x0, page_height - y1, x1, page_height - y0) #flip y axis


def visualize_bboxes(open_doc, table_data: dict, output_path: str = "bbox_visualization_final.pdf"):
    """
        Draw red bounding boxes from the parser on the original PDF.
        Draw blue boxes as extracted text clip rects.
    """
    #use opened pdf
    #pages where we have boxes
    for page_num, tables in table_data.items():
        page_index = page_num - 1 #indexing from 0
        if page_index >= len(open_doc):
            print("Page does not exist.")
            continue

        page = open_doc[page_index]
        page_rect = page.rect

        #sort bboxes by y-axis
        tables.sort(key=lambda b: b["bbox"][1])
        current_y = page_rect.y0

        for i, table in enumerate(tables):
            bbox = table["bbox"]

            #blue rect - above text
            if current_y < bbox[1]:
                clip_rect = pymupdf.Rect(page_rect.x0+0.5, current_y+0.5, page_rect.x1-0.5, bbox[1]-0.5)
                page.draw_rect(clip_rect, color=(0, 0, 1), width=1.5) #blue rect
                page.insert_text((clip_rect.x0 + 5, clip_rect.y0 + 15),f"text_above {i + 1}",color=(0, 0, 1), fontsize=8)

            #red rect - table
            rect = pymupdf.Rect(bbox[0], bbox[1], bbox[2], bbox[3])
            page.draw_rect(rect, color=(1, 0, 0), width=2)
            page.insert_text((bbox[0] + 5, bbox[1] + 15),f"Table {table["id"]}",color=(1, 0, 0), fontsize=8)

            #blue rect below table
            if bbox[3] < page_rect.y1:
                clip_rect = pymupdf.Rect(page_rect.x0+0.5, bbox[3]+0.5, page_rect.x1-0.5, page_rect.y1-0.5)
                page.draw_rect(clip_rect, color=(0, 0, 1), width=1.5) #blue rect
                page.insert_text((clip_rect.x0 + 5, clip_rect.y0 + 15),f"text_below {i + 1}",color=(0, 0, 1), fontsize=8)

            current_y = bbox[3]

    #save new pdf with rects
    open_doc.save(output_path)
    open_doc.close()
    print(f"Visualization saved to {output_path}")


def find_caption_and_table_id(text: str, is_above: bool = False) -> tuple:
    """
        Finds table caption and id from caption, returns (caption, table_id).
    """
    #find "Table X:" and extract number and caption
    is_figure = False
    match = re.search(r'Table\s+(\d+)[.:]?\s+', text, re.IGNORECASE)
    if not match:
        print("neni match")

        #is figure match
        match = re.search(r'Figure\s+(\d+)[.:]?\s+', text, re.IGNORECASE)
        if not match:
            return None, None
        else:
            is_figure = True


    table_id = int(match.group(1)) #"1", "2", "3", ...

    print("je match", is_above, table_id)

    start = match.start()

    #find end of the caption
    if is_above:
        #take the remainder of the text after match
        caption = text[start:].strip()
        print("above caption", caption, "endC")

        if caption:
            #max 4 lines above table
            caption_lines = caption.split('\n')
            print("how many lines", len(caption_lines))

            if len(caption_lines) > 4:
                return None, None

    else:
        #if it is on the first line below table, else invalid
        if start > 0 and text[:start].strip() != "":
            return None, None

        #find first \n\n and .\n, which is sooner, it will mark the end of the caption
        end1 = text.find('\n\n', start)
        end2 = text.find('.\n', start)
        ends = [e for e in [end1, end2] if e != -1]
        end = min(ends) if ends else len(text)
        caption = text[start:end].strip()
        print("below caption", caption)

    #return caption is figure to filter out non-tables
    if is_figure:
        print("figure detected", table_id)
        return "figure", table_id

    return caption, table_id


def filter_text_by_y(words, y_start, y_end):
    """
        Filter words by y-axis.
    """
    filtered = []
    for word in words:
        y0 = word[1]
        y1 = word[3]
        if y_start <= y0 <= y_end or y_start <= y1 <= y_end:
            filtered.append(word)
    return filtered


def build_text_from_words(words, is_above=False):
    """
        Join extracted text on the page from positions.
    """
    words.sort(key=lambda w: (w[1], w[0]))
    text_parts = []
    current_y = None
    word_count = 0

    for word in words:
        y0 = word[1]
        text = word[4]
        if current_y is None or abs(y0 - current_y) > 5:
            if current_y is not None:
                text_parts.append("\n")
            current_y = y0
        else:
            text_parts.append(" ")
        text_parts.append(text)
        word_count += 1

    if is_above: #delete first "word_count" words, to ease the further processing
        for i in range(word_count):
            del words[0]

    return "".join(text_parts).strip()


def extract_text(table_data: dict, opened_doc):
    """
       Extract text outside of detected table bboxes.
    """
    text_by_page = {}
    table_id = None

    for page_index in range(len(opened_doc)):
        page = opened_doc[page_index]
        page_num = page_index + 1
        page_rect = page.rect #page dimensions

        #if no boxes, extract whole page, else extract only parts
        if not page_num in table_data:
            text_by_page[page_num] = page.get_text("text")
            continue

        page_tables = table_data[page_num]

        #sort boxes by y-position for filtering by table boxes
        page_tables.sort(key=lambda b: b["bbox"][1])

        #extract text between tables
        text_parts = []
        current_y = page_rect.y0 #top of the page

        page_text = page.get_text("words") #whole page


        for i,table in enumerate(page_tables):
            caption = f"Table -1" #default caption
            bbox = table["bbox"]
            is_figure = False

            #extract text above the table
            if current_y < bbox[1]:
                #extract words by using positions
                words_above = filter_text_by_y(page_text, current_y, bbox[1])
                text_above = build_text_from_words(words_above, is_above=True)
                #print(f"txet above, page {page_index}",text_above)

                if text_above.strip():
                    #find caption and table id
                    caption, table_id = find_caption_and_table_id(text_above, is_above=True)
                    if caption == "figure":
                        is_figure = True
                    print("found?", table_id, caption)

                    if caption:
                        text_above = text_above.replace(caption, "").strip()

                    text_parts.append(text_above)


            #if not found above, check text under the table for caption
            if not table_id and not is_figure and bbox[3] < page_rect.y1:
                below_bound = page_tables[i+1]["bbox"][1] if i+1 < len(page_tables) else page_rect.y1
                words_below = filter_text_by_y(page_text, bbox[3], below_bound)
                text_below = build_text_from_words(words_below)
                if text_below.strip():
                    #find caption and table id under the table
                    caption, table_id = find_caption_and_table_id(text_below, is_above=False)

                    if caption != "figure":
                        is_figure = False

            if is_figure: #remove table, because it is a figure
                del page_tables[i]
                print("removing table",table,"on page", page_num)

            #add found caption nad table id to the tables
            page_tables[i]["id"] = f"{table_id if table_id else -1}"
            page_tables[i]["caption"] = caption

            #skip table part, skip to the end of the table
            current_y = bbox[3]

        #extract text under the last table
        if current_y < page_rect.y1:
            clip_rect = pymupdf.Rect(page_rect.x0, current_y, page_rect.x1, page_rect.y1)
            text_below = page.get_text(clip=clip_rect)
            if text_below.strip():
                text_parts.append(text_below)

        #join all the text
        text_by_page[page_num] = "\n".join(text_parts)

    return text_by_page


def save_extracted_data(pdf_path: str, text_by_page: dict, tables_data: list, output_path: str):
    """
        Save extracted data to JSON.
    """
    doc = {
        "source": Path(pdf_path).name,
        "pages": []
    }

    #process every page
    for page_num, text in text_by_page.items():
        page_data = {
            "page": page_num,
            "text": text,
            "tables": []
        }

        #add tables on this page
        for table in tables_data:
            if table["page"] == page_num:
                page_data["tables"].append({
                    "id": f"table_{len(page_data['tables']) + 1}",
                    "data": table["data"]
                })

        doc["pages"].append(page_data)

    #save as json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(f"Result saved to {output_path}, {len(doc['pages'])} pages, {sum(len(p['tables']) for p in doc['pages'])} tables.")


if __name__ == "__main__":
    #"attention is all you need" paper
    pdf_path = "../data/raw/attention_is_all_you_need.pdf"

    #open pdf with pymupdf
    doc = pymupdf.open(pdf_path)

    #table_data = extract_tables(pdf_path, doc)
    table_data = {1: [{'bbox': (126.88199999999998, 100.48512319999998, 485.1145184199999, 316.7226972), 'content': [{0: '', 1: 'scholarly works.', 2: ''}, {0: '', 1: 'Attention Is All You Need', 2: ''}, {0: 'Ashish Vaswani∗', 1: 'Noam Shazeer∗', 2: 'Niki Parmar∗\nJakob Uszkoreit∗'}, {0: 'Google Brain', 1: 'Google Brain', 2: 'Google Research\nGoogle Research'}, {0: 'avaswani@google.com', 1: 'noam@google.com', 2: 'nikip@google.com\nusz@google.com'}, {0: 'Llion Jones∗', 1: 'Aidan N. Gomez∗ †', 2: 'Łukasz Kaiser∗'}, {0: 'Google Research', 1: 'University of Toronto', 2: 'Google Brain'}, {0: 'llion@google.com', 1: 'aidan@cs.toronto.edu', 2: 'lukaszkaiser@google.com'}]}], 6: [{'bbox': (124.54699999999991, 116.38332159999993, 487.45463019999994, 183.56592160000002), 'content': [{0: 'Layer Type', 1: 'Complexity per Layer', 2: 'Sequential', 3: 'Maximum Path Length'}, {0: '', 1: '', 2: 'Operations', 3: ''}, {0: 'Self-Attention', 1: 'O(n2 · d)', 2: 'O(1)', 3: 'O(1)'}, {0: 'Recurrent', 1: 'O(n · d2)', 2: 'O(n)', 3: 'O(n)'}, {0: 'Convolutional', 1: 'O(k · n · d2)', 2: 'O(1)', 3: 'O(logk(n))'}, {0: 'Self-Attention (restricted)', 1: 'O(r · n · d)', 2: 'O(1)', 3: 'O(n/r)'}]}], 8: [{'bbox': (136.671, 105.94732160000001, 473.0951582, 240.2929216), 'content': [{0: 'Model', 1: '', 2: '', 3: ''}, {0: '', 1: 'EN-DE', 2: 'EN-FR', 3: 'EN-DE\nEN-FR'}, {0: 'ByteNet [18]', 1: '23.75', 2: '', 3: ''}, {0: 'Deep-Att + PosUnk [39]', 1: '', 2: '39.2', 3: '1.0 · 1020'}, {0: 'GNMT + RL [38]', 1: '24.6', 2: '39.92', 3: '2.3 · 1019\n1.4 · 1020'}, {0: 'ConvS2S [9]', 1: '25.16', 2: '40.46', 3: '9.6 · 1018\n1.5 · 1020'}, {0: 'MoE [32]', 1: '26.03', 2: '40.56', 3: '2.0 · 1019\n1.2 · 1020'}, {0: 'Deep-Att + PosUnk Ensemble [39]', 1: '', 2: '40.4', 3: '8.0 · 1020'}, {0: 'GNMT + RL Ensemble [38]', 1: '26.30', 2: '41.16', 3: '1.8 · 1020\n1.1 · 1021'}, {0: 'ConvS2S Ensemble [9]', 1: '26.36', 2: '41.29', 3: '7.7 · 1019\n1.2 · 1021'}, {0: 'Transformer (base model)', 1: '27.3', 2: '38.1', 3: '3.3 · 1018'}, {0: 'Transformer (big)', 1: '28.4', 2: '41.8', 3: '2.3 · 1019'}]}], 9: [{'bbox': (107.75999999999999, 129.56073916994853, 509.03999999999996, 384.6034534989397), 'content': [{0: '', 1: 'train\nN\nh\ndk\ndv\nPdrop\nϵls\ndmodel\ndff\nsteps', 2: 'PPL\nBLEU\nparams\n×106\n(dev)\n(dev)'}, {0: 'base', 1: '6\n512\n2048\n8\n64\n64\n0.1\n0.1\n100K', 2: '4.92\n25.8\n65'}, {0: '(A)', 1: '1\n512\n512\n4\n128\n128\n16\n32\n32\n32\n16\n16', 2: '5.29\n24.9\n5.00\n25.5\n4.91\n25.8\n5.01\n25.4'}, {0: '(B)', 1: '16\n32', 2: '5.16\n25.1\n58\n5.01\n25.4\n60'}, {0: '(C)', 1: '2\n4\n8\n256\n32\n32\n1024\n128\n128\n1024\n4096', 2: '6.11\n23.7\n36\n5.19\n25.3\n50\n4.88\n25.5\n80\n5.75\n24.5\n28\n4.66\n26.0\n168\n5.12\n25.4\n53\n4.75\n26.2\n90'}, {0: '(D)', 1: '0.0\n0.2\n0.0\n0.2', 2: '5.77\n24.6\n4.95\n25.5\n4.67\n25.3\n5.47\n25.7'}, {0: '(E)', 1: 'positional embedding instead of sinusoids', 2: '4.92\n25.7'}, {0: 'big', 1: '6\n1024\n4096\n16\n0.3\n300K', 2: '4.33\n26.4\n213'}]}], 10: [{'bbox': (144.72, 93.5716449560739, 467.28, 236.80823992729472), 'content': [{0: 'Parser', 1: 'Training', 2: 'WSJ 23 F1'}, {0: 'Vinyals & Kaiser el al. (2014) [37]\nPetrov et al. (2006) [29]\nZhu et al. (2013) [40]\nDyer et al. (2016) [8]', 1: 'WSJ only, discriminative\nWSJ only, discriminative\nWSJ only, discriminative\nWSJ only, discriminative', 2: '88.3\n90.4\n90.4\n91.7'}, {0: 'Transformer (4 layers)', 1: 'WSJ only, discriminative', 2: '91.3'}, {0: 'Zhu et al. (2013) [40]\nHuang & Harper (2009) [14]\nMcClosky et al. (2006) [26]\nVinyals & Kaiser el al. (2014) [37]', 1: 'semi-supervised\nsemi-supervised\nsemi-supervised\nsemi-supervised', 2: '91.3\n91.3\n92.1\n92.1'}, {0: 'Transformer (4 layers)', 1: 'semi-supervised', 2: '92.7'}, {0: 'Luong et al. (2015) [23]\nDyer et al. (2016) [8]', 1: 'multi-task\ngenerative', 2: '93.0\n93.3'}]}], 13: [{'bbox': (505.6476037, 302.19648613185, 676.47722264284, 683.3613509938499), 'content': [{0: 'It', 1: 'It'}, {0: 'is', 1: 'is'}, {0: 'in', 1: 'in'}, {0: 'this', 1: 'this'}, {0: 'spirit', 1: 'spirit'}, {0: 'that', 1: 'that'}, {0: '', 1: ''}, {0: 'majority', 1: 'a m\najority'}, {0: 'of', 1: 'of'}, {0: 'American', 1: 'American'}, {0: 'governments', 1: 'governments'}, {0: 'have', 1: 'have'}, {0: 'passed', 1: 'passed'}, {0: 'new', 1: 'new'}, {0: 'laws', 1: 'laws'}, {0: 'since', 1: 'since'}, {0: '2009', 1: '2009'}, {0: 'making', 1: 'making'}, {0: 'the', 1: 'the'}, {0: 'registration', 1: 'registration'}, {0: 'or', 1: 'or'}, {0: 'voting', 1: 'voting'}, {0: 'process', 1: 'process'}, {0: 'more', 1: 'more'}, {0: 'difficult', 1: 'difficult'}, {0: '.', 1: ''}, {0: '<EOS>', 1: '. <\nEOS>'}, {0: '<pad>', 1: '<pad>'}, {0: '<pad>', 1: '<pad>'}, {0: '<pad>', 1: '<pad>'}, {0: '<pad>', 1: '<pad>'}, {0: '<pad>', 1: '<pad>'}, {0: '<pad>', 1: '<pad>'}]}], 14: [{'bbox': (216.490619178, 288.0, 621.32350747304, 682.09142640815), 'content': [{0: 'The', 1: 'The', 2: 'The', 3: 'The'}, {0: 'Law', 1: 'Law', 2: 'Law', 3: 'Law'}, {0: 'will', 1: 'will', 2: 'will', 3: 'will'}, {0: 'never', 1: 'never', 2: 'never', 3: 'never'}, {0: 'be', 1: 'be', 2: 'be', 3: 'be'}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: 'perfect\n,\nbut\nits\napplication\nshould', 1: 'perfect\n, b\nut\nits\napplication\nshould', 2: 'perfect\n,\nbut\nits\napplication\nshould\nInput-Input Layer5', 3: 'perfect\n, b\nut\nits\napplication\nshould'}, {0: '', 1: '', 2: 'be', 3: 'be'}, {0: 'be', 1: 'be', 2: '', 3: ''}, {0: '', 1: '', 2: 'just', 3: 'just'}, {0: 'just', 1: 'just', 2: '', 3: ''}, {0: '', 1: '', 2: '-', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '-', 1: '', 2: '', 3: '- t'}, {0: 'this', 1: '- t\nhis', 2: 'this', 3: 'his'}, {0: '', 1: '', 2: 'is', 3: 'is'}, {0: 'is', 1: 'is', 2: '', 3: ''}, {0: '', 1: '', 2: 'what', 3: 'what'}, {0: 'what', 1: 'what', 2: '', 3: ''}, {0: '', 1: '', 2: 'we', 3: 'we'}, {0: 'we', 1: 'we', 2: '', 3: ''}, {0: '', 1: '', 2: 'are', 3: 'are'}, {0: 'are', 1: 'are', 2: '', 3: ''}, {0: '', 1: '', 2: 'missing', 3: 'missing'}, {0: 'missing', 1: 'missing', 2: '', 3: ''}, {0: '', 1: '', 2: ',', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: ',', 1: '', 2: '', 3: ', i'}, {0: '', 1: ', i', 2: 'in', 3: ''}, {0: 'in', 1: '', 2: '', 3: 'n m'}, {0: 'my', 1: 'n m\ny', 2: 'my', 3: 'y'}, {0: '', 1: '', 2: 'opinion', 3: 'opinion'}, {0: 'opinion', 1: 'opinion', 2: '', 3: ''}, {0: '', 1: '', 2: '.', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '.', 1: '', 2: '', 3: '. <'}, {0: '<EOS>', 1: '. <\nEOS>', 2: '<EOS>', 3: 'EOS>'}, {0: '', 1: '', 2: '<pad>', 3: '<pad>'}, {0: '<pad>', 1: '<pad>', 2: '', 3: ''}]}], 15: [{'bbox': (202.02983416000004, 286.765759931, 606.8898545488801, 677.7164747507001), 'content': [{0: 'The', 1: 'The', 2: 'The', 3: 'The'}, {0: 'Law', 1: 'Law', 2: 'Law', 3: 'Law'}, {0: 'will', 1: 'will', 2: 'will', 3: 'will'}, {0: 'never', 1: 'never', 2: 'never', 3: 'never'}, {0: 'be', 1: 'be', 2: 'be', 3: 'be'}, {0: 'perfect', 1: 'perfect', 2: 'perfect\nInput-Input Layer5', 3: 'perfect'}, {0: ',', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: '', 1: '', 2: '', 3: ''}, {0: 'but\nits\napplication\nshould', 1: ', b\nut\nits\napplication\nshould', 2: ',\nbut\nits\napplication\nshould', 3: ', b\nut\nits\napplication\nshould'}, {0: 'be', 1: 'be', 2: 'be', 3: 'be'}, {0: 'just', 1: 'just', 2: 'just', 3: 'just'}, {0: '-', 1: '', 2: '', 3: ''}, {0: 'this', 1: '- t\nhis', 2: '-\nthis', 3: '- t\nhis'}, {0: 'is', 1: 'is', 2: 'is', 3: 'is'}, {0: 'what', 1: 'what', 2: 'what', 3: 'what'}, {0: 'we', 1: 'we', 2: 'we', 3: 'we'}, {0: 'are', 1: 'are', 2: 'are', 3: 'are'}, {0: 'missing', 1: 'missing', 2: 'missing', 3: 'missing'}, {0: ',', 1: '', 2: '', 3: ''}, {0: 'in', 1: ', i', 2: ',', 3: ', i'}, {0: 'my', 1: 'n m\ny', 2: 'in\nmy', 3: 'n m\ny'}, {0: 'opinion', 1: 'opinion', 2: 'opinion', 3: 'opinion'}, {0: '.', 1: '', 2: '', 3: ''}, {0: '<EOS>', 1: '. <\nEOS>', 2: '.\n<EOS>', 3: '. <\nEOS>'}, {0: '<pad>', 1: '<pad>', 2: '<pad>', 3: '<pad>'}]}]}


    #print("table bboxes",table_bboxes)
    print("table data", table_data)

    text_by_page = extract_text(table_data, doc)

    #print(text_by_page)
    print("new data",table_data)

    #save final results to json
    #save_extracted_data(
    #    pdf_path=pdf_path,
    #    text_by_page=text_by_page,
    #    tables_data=table_data,
    #    output_path="../chunking/extracted_document.json"
    #)

    #visualize final detections
    visualize_bboxes(doc, table_data)