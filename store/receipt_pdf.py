"""PDF Receipt Generator for Reeves Boutique POS.

Generates supermarket-style thermal receipts (80mm and 58mm) using ReportLab.
Returns a BytesIO buffer suitable for streaming in an HTTP response.
"""
import io
from decimal import Decimal
from django.utils import timezone

from reportlab.lib.pagesizes import portrait
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from .models import SiteSettings, Payment


def money_str(val, currency='KES'):
    try:
        d = Decimal(str(val or '0'))
        return f"{currency} {d:,.2f}"
    except Exception:
        return f"{currency} 0.00"


def generate_receipt_pdf(order, size='80'):
    """Generate a thermal receipt PDF for the given Order.

    size: '80' for 80mm wide paper, '58' for 58mm wide paper.
    Returns: BytesIO object containing PDF bytes.
    """
    settings = SiteSettings.get()
    currency = settings.currency or 'KES'

    # Width in mm: 80mm or 58mm
    paper_width_mm = 80 if size == '80' else 58
    margin_mm = 3
    usable_width_mm = paper_width_mm - (2 * margin_mm)

    paper_width = paper_width_mm * mm
    margin = margin_mm * mm
    usable_width = usable_width_mm * mm

    # Estimate height dynamically based on items and metadata so the receipt
    # looks continuous and natural like real thermal paper roll.
    item_count = order.items.count()
    payment_count = order.payments.count()
    base_height_mm = 110 + (item_count * 12) + (payment_count * 8)
    estimated_height = max(160 * mm, base_height_mm * mm)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=(paper_width, estimated_height),
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin + 2 * mm,
        bottomMargin=margin + 2 * mm,
    )

    styles = getSampleStyleSheet()

    # Font sizes scaled for 80mm vs 58mm
    is_58 = (size == '58')
    fs_title = 11 if is_58 else 13
    fs_header = 9 if is_58 else 10
    fs_body = 7.5 if is_58 else 8.5
    fs_small = 6.5 if is_58 else 7.5

    style_store = ParagraphStyle(
        'StoreName',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_title,
        leading=fs_title + 3,
        alignment=TA_CENTER,
        textColor=colors.black,
    )
    style_sub = ParagraphStyle(
        'StoreSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_small,
        leading=fs_small + 3,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#333333'),
    )
    style_h1 = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_header,
        leading=fs_header + 3,
        alignment=TA_CENTER,
        textColor=colors.black,
    )
    style_meta_l = ParagraphStyle(
        'MetaL',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_small,
        leading=fs_small + 3,
        alignment=TA_LEFT,
    )
    style_meta_r = ParagraphStyle(
        'MetaR',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_small,
        leading=fs_small + 3,
        alignment=TA_RIGHT,
    )
    style_cell_l = ParagraphStyle(
        'CellL',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_body,
        leading=fs_body + 2,
        alignment=TA_LEFT,
    )
    style_cell_sku = ParagraphStyle(
        'CellSku',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_small,
        leading=fs_small + 2,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#555555'),
    )
    style_cell_r = ParagraphStyle(
        'CellR',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_body,
        leading=fs_body + 2,
        alignment=TA_RIGHT,
    )
    style_th_l = ParagraphStyle(
        'THL',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_small,
        leading=fs_small + 2,
        alignment=TA_LEFT,
    )
    style_th_r = ParagraphStyle(
        'THR',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_small,
        leading=fs_small + 2,
        alignment=TA_RIGHT,
    )
    style_total_l = ParagraphStyle(
        'TotL',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_body,
        leading=fs_body + 3,
        alignment=TA_LEFT,
    )
    style_total_r = ParagraphStyle(
        'TotR',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=fs_body,
        leading=fs_body + 3,
        alignment=TA_RIGHT,
    )
    style_grand_l = ParagraphStyle(
        'GrandL',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_header + 1,
        leading=fs_header + 4,
        alignment=TA_LEFT,
    )
    style_grand_r = ParagraphStyle(
        'GrandR',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_header + 1,
        leading=fs_header + 4,
        alignment=TA_RIGHT,
    )
    style_thanks = ParagraphStyle(
        'Thanks',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=fs_header,
        leading=fs_header + 3,
        alignment=TA_CENTER,
    )

    story = []

    # 1. Header & Store Info
    story.append(Paragraph(settings.store_name.upper(), style_store))
    if settings.tagline:
        story.append(Paragraph(settings.tagline, style_sub))
    if settings.address:
        story.append(Paragraph(settings.address, style_sub))
    contacts = []
    if settings.phone:
        contacts.append(f"Tel: {settings.phone}")
    if settings.contact_email:
        contacts.append(settings.contact_email)
    if contacts:
        story.append(Paragraph(" · ".join(contacts), style_sub))

    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("SALES RECEIPT", style_h1))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceBefore=2, spaceAfter=3))

    # 2. Receipt Metadata
    created_local = timezone.localtime(order.created_at) if order.created_at else timezone.now()
    meta_rows = [
        [Paragraph("RECEIPT NO", style_meta_l), Paragraph(order.number, style_meta_r)],
        [Paragraph("DATE", style_meta_l), Paragraph(created_local.strftime('%d/%m/%Y'), style_meta_r)],
        [Paragraph("TIME", style_meta_l), Paragraph(created_local.strftime('%I:%M %p'), style_meta_r)],
    ]
    if order.served_by:
        cashier_name = order.served_by.get_full_name() or order.served_by.username
        meta_rows.append([Paragraph("CASHIER", style_meta_l), Paragraph(cashier_name, style_meta_r)])
    if order.customer_name and order.customer_name.strip() not in ('Walk-in customer', ''):
        meta_rows.append([Paragraph("CUSTOMER", style_meta_l), Paragraph(order.customer_name, style_meta_r)])
    if order.phone:
        meta_rows.append([Paragraph("PHONE", style_meta_l), Paragraph(order.phone, style_meta_r)])

    col_meta_w = usable_width / 2.0
    t_meta = Table(meta_rows, colWidths=[col_meta_w, col_meta_w])
    t_meta.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5),
    ]))
    story.append(t_meta)
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.black, dash=(2, 2), spaceBefore=3, spaceAfter=3))

    # 3. Item Lines
    # Column widths for 4 columns: [Item, Qty, Unit Price, Total]
    if is_58:
        # usable ~ 52mm = ~147 pt
        col_w = [68 * mm * 0.40, 52 * mm * 0.16, 52 * mm * 0.22, 52 * mm * 0.22]
    else:
        # usable ~ 74mm = ~210 pt: Item (92pt), Qty (24pt), Price (46pt), Total (48pt)
        col_w = [92, 24, 46, 48]

    items_data = [
        [
            Paragraph("ITEM", style_th_l),
            Paragraph("QTY", style_th_r),
            Paragraph("PRICE", style_th_r),
            Paragraph("TOTAL", style_th_r)
        ]
    ]

    for item in order.items.all():
        item_text = f"<b>{item.product_name}</b>"
        if item.product_sku:
            item_text += f"<br/><font color='#555555'>SKU: {item.product_sku}</font>"
        items_data.append([
            Paragraph(item_text, style_cell_l),
            Paragraph(str(item.quantity), style_cell_r),
            Paragraph(f"{item.price:,.2f}", style_cell_r),
            Paragraph(f"{item.subtotal:,.2f}", style_cell_r),
        ])

    t_items = Table(items_data, colWidths=col_w)
    t_items.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, colors.black),
    ]))
    story.append(t_items)
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.black, dash=(2, 2), spaceBefore=4, spaceAfter=3))

    # 4. Totals Breakdown
    totals_rows = [
        [Paragraph("SUBTOTAL", style_total_l), Paragraph(money_str(order.subtotal, currency), style_total_r)],
    ]
    if order.discount and order.discount > 0:
        totals_rows.append([
            Paragraph("DISCOUNT", style_total_l),
            Paragraph(f"-{money_str(order.discount, currency)}", style_total_r)
        ])
    if order.tax and order.tax > 0:
        rate_str = f" ({settings.tax_rate}%)" if settings.tax_rate else ""
        totals_rows.append([
            Paragraph(f"VAT / TAX{rate_str}", style_total_l),
            Paragraph(money_str(order.tax, currency), style_total_r)
        ])
    if order.shipping and order.shipping > 0:
        totals_rows.append([
            Paragraph("DELIVERY", style_total_l),
            Paragraph(money_str(order.shipping, currency), style_total_r)
        ])

    totals_rows.append([
        Paragraph("GRAND TOTAL", style_grand_l),
        Paragraph(money_str(order.total, currency), style_grand_r)
    ])

    t_totals = Table(totals_rows, colWidths=[col_meta_w, col_meta_w])
    t_totals.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('LINEABOVE', (0, -1), (-1, -1), 0.6, colors.black),
    ]))
    story.append(t_totals)
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.black, spaceBefore=3, spaceAfter=3))

    # 5. Payment Tenders & Change
    payment_rows = []
    payments = list(order.payments.all())
    if payments:
        for p in payments:
            method_label = p.get_method_display().upper()
            if p.reference:
                method_label += f" ({p.reference})"
            payment_rows.append([
                Paragraph(f"Tender · {method_label}", style_meta_l),
                Paragraph(money_str(p.amount, currency), style_meta_r)
            ])
            if p.amount_paid is not None and p.amount_paid > p.amount:
                payment_rows.append([
                    Paragraph("Cash Handed", style_meta_l),
                    Paragraph(money_str(p.amount_paid, currency), style_meta_r)
                ])
            if p.change_given is not None and p.change_given > 0:
                payment_rows.append([
                    Paragraph("CHANGE RETURNED", style_grand_l),
                    Paragraph(money_str(p.change_given, currency), style_grand_r)
                ])
    else:
        method_name = (order.get_pos_payment_method_display() if order.pos_payment_method
                       else order.get_payment_method_display()).upper()
        payment_rows.append([
            Paragraph(f"PAYMENT ({method_name})", style_meta_l),
            Paragraph(order.get_payment_status_display().upper(), style_meta_r)
        ])

    t_pay = Table(payment_rows, colWidths=[col_meta_w, col_meta_w])
    t_pay.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5),
    ]))
    story.append(t_pay)
    story.append(HRFlowable(width="100%", thickness=0.6, color=colors.black, spaceBefore=3, spaceAfter=4))

    # 6. Footer Notes
    story.append(Paragraph("THANK YOU FOR YOUR PATRONAGE!", style_thanks))
    story.append(Paragraph("Please keep this receipt for exchanges or returns.", style_sub))
    if settings.social_whatsapp:
        story.append(Paragraph(f"WhatsApp: {settings.social_whatsapp}", style_sub))
    if settings.footer_text:
        story.append(Paragraph(settings.footer_text, style_sub))

    doc.build(story)
    buffer.seek(0)
    return buffer
