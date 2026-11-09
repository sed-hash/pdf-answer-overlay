import os
import io
import zipfile
import json
import streamlit as st
import pymupdf

st.set_page_config(
    page_title="講義資料 PDF解答自動合成Webアプリ",
    page_icon="📄",
    layout="centered"
)

def get_font_settings():
    """Returns Japanese font parameters compatible with Windows and Linux/Cloud."""
    windows_fonts = [
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\YuGothM.ttc",
    ]
    for wf in windows_fonts:
        if os.path.exists(wf):
            return wf, "file"
    # Linux / Cloud fallback
    return "japan", "builtin"

def process_pdf_bytes(pdf_bytes, text_color_rgb):
    """Processes in-memory PDF bytes with char-level precision and returns modified PDF bytes with stats."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    jp_font_target, jp_font_type = get_font_settings()
    
    total_pages = len(doc)
    modified_pages = 0
    total_answers = 0
    summary_answers = []

    for pno in range(total_pages):
        page = doc[pno]
        page_rect = page.rect
        
        # 1. Collect white fill rects (masks)
        white_rects = []
        for d in page.get_drawings():
            fill = d.get("fill")
            r = d.get("rect")
            if fill is not None and len(fill) >= 3:
                if fill[0] > 0.9 and fill[1] > 0.9 and fill[2] > 0.9:
                    if r.width < page_rect.width * 0.9 or r.height < page_rect.height * 0.9:
                        white_rects.append(r)
                        
        if not white_rects:
            continue

        # 2. Extract hidden characters with char-level accuracy
        try:
            d_json = json.loads(page.get_text("rawjson"))
        except Exception:
            continue

        page_has_hidden = False
        page_answers = []

        for b in d_json.get("blocks", []):
            for l in b.get("lines", []):
                curr_word = ""
                for s in l.get("spans", []):
                    size = s.get("size", 12.0)
                    for c in s.get("chars", []):
                        ch = c.get("c", "")
                        c_rect = pymupdf.Rect(c["bbox"])
                        c_center = pymupdf.Point((c_rect.x0 + c_rect.x1) / 2.0, (c_rect.y0 + c_rect.y1) / 2.0)
                        
                        is_hidden = False
                        for wr in white_rects:
                            if c_center in wr or ((c_rect & wr).get_area() > 0.4 * c_rect.get_area()):
                                is_hidden = True
                                break
                                
                        if is_hidden:
                            page_has_hidden = True
                            curr_word += ch
                            
                            # Render character directly at exact character origin
                            if ch and not ch.isspace():
                                origin = pymupdf.Point(c["origin"])
                                if ord(ch) < 128:
                                    # English / ASCII: use standard Helvetica for exact kerning
                                    page.insert_text(
                                        origin,
                                        ch,
                                        fontsize=size,
                                        fontname="helv",
                                        color=text_color_rgb
                                    )
                                else:
                                    # Japanese / CJK: use Meiryo/YuGoth on Windows, 'japan' on Linux
                                    if jp_font_type == "file":
                                        page.insert_text(
                                            origin,
                                            ch,
                                            fontsize=size,
                                            fontname="jp_font",
                                            fontfile=jp_font_target,
                                            color=text_color_rgb
                                        )
                                    else:
                                        page.insert_text(
                                            origin,
                                            ch,
                                            fontsize=size,
                                            fontname=jp_font_target,
                                            color=text_color_rgb
                                        )
                        else:
                            if curr_word.strip():
                                page_answers.append(curr_word.strip())
                                curr_word = ""
                if curr_word.strip():
                    page_answers.append(curr_word.strip())

        if page_has_hidden:
            modified_pages += 1
            total_answers += len(page_answers)
            for ans in page_answers:
                summary_answers.append(f"P{pno+1}: {ans}")

    output_buffer = io.BytesIO()
    doc.save(output_buffer, deflate=True)
    doc.close()
    output_buffer.seek(0)
    
    return output_buffer.getvalue(), modified_pages, total_pages, total_answers, summary_answers

# --- UI Header ---
st.title("📄 講義資料 PDF解答自動合成アプリ")
st.write("講義スライド等のPDFをアップロードすると、空欄（白マスク）で隠された解答テキストを検出し、元のレイアウトそのままに赤字で直接合成したPDFを出力します。")

# --- Options in Sidebar or Expander ---
with st.expander("⚙️ オプション設定", expanded=False):
    color_choice = st.color_picker("解答テキストの文字色", "#D90D0D")
    # Convert HEX to RGB tuple (0.0 to 1.0)
    h = color_choice.lstrip("#")
    rgb = tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

# --- File Uploader ---
uploaded_files = st.file_uploader(
    "PDFファイルを選択またはドラッグ＆ドロップ（複数ファイル対応）",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    st.write(f"📁 選択されたファイル数: **{len(uploaded_files)} 件**")
    
    if st.button("🚀 解答入りPDFを一括生成する", type="primary"):
        processed_results = []
        progress_bar = st.progress(0)
        
        for idx, file in enumerate(uploaded_files):
            pdf_bytes = file.read()
            with st.spinner(f"処理中: {file.name}..."):
                out_bytes, mod_pages, tot_pages, total_ans, ans_list = process_pdf_bytes(pdf_bytes, rgb)
                
            base, _ = os.path.splitext(file.name)
            out_filename = f"{base}_解答入り.pdf"
            
            processed_results.append({
                "filename": out_filename,
                "orig_filename": file.name,
                "bytes": out_bytes,
                "mod_pages": mod_pages,
                "tot_pages": tot_pages,
                "total_ans": total_ans,
                "ans_list": ans_list
            })
            progress_bar.progress((idx + 1) / len(uploaded_files))
            
        st.success(f"🎉 全 {len(processed_results)} 件のPDF処理が完了しました！")
        
        # --- Download Section ---
        st.markdown("### 📥 ダウンロード")
        
        # ZIP download if multiple files
        if len(processed_results) > 1:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for item in processed_results:
                    zip_file.writestr(item["filename"], item["bytes"])
            zip_buffer.seek(0)
            
            st.download_button(
                label="📦 すべての解答入りPDFを一括ダウンロード (.zip)",
                data=zip_buffer,
                file_name="講義資料_解答入り一括.zip",
                mime="application/zip",
                type="primary"
            )
            st.divider()

        # Individual file cards
        for item in processed_results:
            col1, col2 = st.columns([3, 2])
            with col1:
                st.write(f"📄 **{item['filename']}**")
                if item["total_ans"] > 0:
                    st.caption(f"✅ {item['mod_pages']}/{item['tot_pages']} ページに合計 {item['total_ans']} 箇所の解答を合成")
                else:
                    st.caption("⚠️ 空欄（隠しテキスト）は見つかりませんでした")
            with col2:
                st.download_button(
                    label=f"⬇️ ダウンロード",
                    data=item["bytes"],
                    file_name=item["filename"],
                    mime="application/pdf",
                    key=item["filename"]
                )
            
            # Show detected answers preview
            if item["ans_list"]:
                with st.expander(f"🔍 検出された解答テキスト（{item['orig_filename']}）"):
                    st.write("、 ".join(item["ans_list"][:20]) + ("..." if len(item["ans_list"]) > 20 else ""))
            st.write("---")

st.markdown("""
---
<div style='text-align: center; color: #888; font-size: 0.85em;'>
講義配布資料 解答合成Webアプリ | Windows Defender等の警告なしでブラウザから安全に利用可能
</div>
""", unsafe_allow_html=True)
