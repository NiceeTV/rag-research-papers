import camelot
import pymupdf
import json
from pathlib import Path

def extract_tables(path: str):
    tables = camelot.read_pdf(path, pages="1-15", flavor="auto")

    #use camelot filter to filter out bad detections, better, but still bad detections
    clean_tables = tables.filter(min_rows=2, min_columns=2).filter(min_accuracy=50)

    #save bounding boxes for each page
    table_bboxes = {}
    table_data = [] #text of the tables

    for table in clean_tables:
        page_num = table.page
        bbox = table._bbox  #PDF coordinates
        if page_num not in table_bboxes:
            table_bboxes[page_num] = []
        table_bboxes[page_num].append(bbox)

        #save content to dataframe
        table_data.append({
            "page": page_num,
            "data": table.df.to_dict(orient="records")
        })


    return table_bboxes, table_data


def convert_camelot_bbox_to_pymupdf(bbox: tuple, page_height: float) -> tuple:
    """
        Convert Camelot coords (starting from top left) to pymupdf (bottom left) for the visualization to be correct.
    """
    x0, y0, x1, y1 = bbox
    return (x0, page_height - y1, x1, page_height - y0) #flip y axis


def visualize_bboxes(pdf_path: str, bboxes_by_page: dict, output_path: str = "bbox_visualization_final.pdf"):
    """
        Draw bounding boxes from the parser on the original PDF.
    """
    #open original pdf
    doc = pymupdf.open(pdf_path)

    #pages where we have boxes
    for page_num, bboxes in bboxes_by_page.items():
        page_index = page_num - 1 #indexing from 0
        if page_index >= len(doc):
            print("Page does not exist.")
            continue

        page = doc[page_index]
        page_height = page.rect.height

        #if there are more boxes
        if isinstance(bboxes, list):
            for bbox in bboxes:
                #convert coords and create rect
                converted_bbox = convert_camelot_bbox_to_pymupdf(bbox, page_height)
                rect = pymupdf.Rect(converted_bbox[0], converted_bbox[1], converted_bbox[2], converted_bbox[3])

                #draw red rect around the table
                page.draw_rect(rect, color=(1, 0, 0), width=2)

        else:
            #only 1 bbox
            rect = pymupdf.Rect(bboxes[0], bboxes[1], bboxes[2], bboxes[3])
            page.draw_rect(rect, color=(1, 0, 0), width=2)

    #save new pdf with rects
    doc.save(output_path)
    doc.close()
    print(f"Visualization saved to {output_path}")


def extract_text(path: str, table_bboxes: dict):
    """
       Extract text outside of detected table bboxes.
    """
    doc = pymupdf.open(path)
    text_by_page = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_index = page_num + 1
        page_height = page.rect.height
        page_rect = page.rect #page dimensions

        #if no boxes, extract whole page
        if page_index not in table_bboxes:
            text_by_page[page_index] = page.get_text("text")
            continue

        #if there are any boxes, extract only parts
        bboxes = table_bboxes[page_index]

        #convert Camelot coords to pymupdf
        converted_bboxes = [convert_camelot_bbox_to_pymupdf(bbox, page_height) for bbox in bboxes]

        #sort boxes by y-position for filtering by table boxes
        converted_bboxes.sort(key=lambda b: b[1])

        #extract text between tables
        text_parts = []
        current_y = page_rect.y0 #top of the page

        for bbox in converted_bboxes:
            #extract text above the table
            if current_y < bbox[1]:
                clip_rect = pymupdf.Rect(page_rect.x0, current_y, page_rect.x1, bbox[1])
                text_above = page.get_text(clip=clip_rect)
                if text_above.strip():
                    text_parts.append(text_above)

            #skip table part, skip to the end of the table
            current_y = bbox[3]

        #extract text under the table
        if current_y < page_rect.y1:
            clip_rect = pymupdf.Rect(page_rect.x0, current_y, page_rect.x1, page_rect.y1)
            text_below = page.get_text(clip=clip_rect)
            if text_below.strip():
                text_parts.append(text_below)

        #join all the text
        text_by_page[page_index] = "\n".join(text_parts)

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

    table_bboxes, table_data = extract_tables(pdf_path)

    print("table bboxes",table_bboxes)
    print("table data", table_data)

    text_by_page = extract_text(pdf_path, table_bboxes)

    #save final results to json
    save_extracted_data(
        pdf_path=pdf_path,
        text_by_page=text_by_page,
        tables_data=table_data,
        output_path="../chunking/extracted_document.json"
    )

    #visualize final detections
    visualize_bboxes(pdf_path, table_bboxes)