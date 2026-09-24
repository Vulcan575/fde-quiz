#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把纯文本题库转换成刷题应用的 questions.js

用法：
    python 转换题库.py 题库数据.txt
    python 转换题库.py 题库数据.txt -o questions.js

源文件格式（每题由 1 行题干 + 若干行选项组成，题与题之间用空行隔开）：

    1|B|单选|提示词工程的主要目标是？
    A. 让AI模型理解更复杂的编程语言
    B. 通过优化输入指令，引导AI模型生成更准确、符合预期的输出
    C. 提升AI模型的运算速度
    D. 减少AI模型训练所需的数据量
    解析：这行是可选的，写了就会出现在应用的解析区

    2|ABD|多选|以下哪些属于飞书的能力？
    A. 云文档
    ...

字段说明：
    题干行 = 题号 | 答案 | 题型 | 题干
      题号  任意正整数，只要不重复
      答案  选项字母，如 "B" 或 "ABD"（大小写都认，顺序无所谓）
      题型  写"单选"或"多选"，只影响应用里的标签显示
    选项行 = 字母 + 分隔符 + 选项文本
      分隔符可以是 ". " 或 "、"，即 "A. xxx" 和 "A、xxx" 都认
      选项字母不限于 ABCD，A-H 都支持

生成的 answer 是 0 基下标：A=0 B=1 C=2 D=3，多选 "ABD" -> [0, 1, 3]
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 题干行：题号|答案|题型|题干
PAT_STEM = re.compile(r'^(\d+)\s*\|\s*([A-Za-z]+)\s*\|\s*(单选|多选)\s*\|\s*(.+)$')
# 选项行：字母 + . 或 、 + 文本
PAT_OPT = re.compile(r'^([A-Za-z])\s*[.、．]\s*(.+)$')
# 解析行（可选）：解析：xxx 或 解析|xxx
PAT_TIP = re.compile(r'^解析\s*[|:：]\s*(.+)$')

MAX_OPTIONS = 8


def parse(src_path):
    """解析源文件，返回 (题目列表, 警告列表)"""
    questions = []
    warnings = []
    cur = None

    for lineno, raw in enumerate(Path(src_path).read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line:
            continue

        m = PAT_STEM.match(line)
        if m:
            no, ans, typ, stem = m.groups()
            letters = [c.upper() for c in ans]
            bad = [c for c in letters if not ('A' <= c <= 'Z')]
            if bad:
                warnings.append(f'第 {lineno} 行：答案 "{ans}" 含非字母字符')
            cur = {
                'id': int(no),
                'q': stem.strip(),
                'type': typ,
                'options': [],
                'answer': [ord(c) - ord('A') for c in letters],
                'explain': '',
                '_line': lineno,
            }
            questions.append(cur)
            continue

        mt = PAT_TIP.match(line)
        if mt and cur is not None:
            cur['explain'] = mt.group(1).strip()
            continue

        mo = PAT_OPT.match(line)
        if mo and cur is not None:
            letter = mo.group(1).upper()
            idx = ord(letter) - ord('A')
            if idx >= MAX_OPTIONS:
                warnings.append(f'第 {lineno} 行：选项字母 {letter} 超出 A-{chr(ord("A") + MAX_OPTIONS - 1)} 范围，已忽略')
                continue
            # 乱序或跳号的选项按字母序归位
            while len(cur['options']) < idx:
                cur['options'].append('')
            if len(cur['options']) == idx:
                cur['options'].append(mo.group(2).strip())
            else:
                cur['options'][idx] = mo.group(2).strip()
            continue

        if cur is None:
            warnings.append(f'第 {lineno} 行：出现在任何题目之前的游离内容，已忽略 -> {line[:40]}')
        else:
            warnings.append(f'第 {lineno} 行：无法识别，已忽略 -> {line[:40]}')

    return questions, warnings


def validate(questions):
    """校验题目，返回 (错误列表, 警告列表)"""
    errors, warnings = [], []

    if not questions:
        errors.append('没有解析出任何题目 —— 检查一下源文件格式，题干行要写成 "题号|答案|题型|题干"')
        return errors, warnings

    seen = {}
    for q in questions:
        if q['id'] in seen:
            errors.append(f'题号 {q["id"]} 重复（第 {seen[q["id"]]} 行 和 第 {q["_line"]} 行）')
        else:
            seen[q['id']] = q['_line']

        if not q['answer']:
            errors.append(f'第 {q["_line"]} 行（题号 {q["id"]}）：没有答案')

        opt_count = len(q['options'])
        if opt_count < 2:
            errors.append(f'第 {q["_line"]} 行（题号 {q["id"]}）：只有 {opt_count} 个选项')
        elif opt_count != 4:
            warnings.append(f'题号 {q["id"]}：{opt_count} 个选项（应用支持，但界面按 4 个调的）')

        if any(not o for o in q['options']):
            errors.append(f'第 {q["_line"]} 行（题号 {q["id"]}）：选项字母跳号，中间有空缺')

        out_of_range = [i for i in q['answer'] if i < 0 or i >= opt_count]
        if out_of_range:
            letters = '、'.join(chr(ord('A') + i) if 0 <= i < 26 else str(i) for i in out_of_range)
            errors.append(f'第 {q["_line"]} 行（题号 {q["id"]}）：答案 {letters} 超出选项范围（只有 {opt_count} 个选项）')

        if len(q['answer']) > 1 and q['type'] == '单选':
            warnings.append(f'题号 {q["id"]}：题型写的是单选，但有 {len(q["answer"])} 个答案')
        if len(q['answer']) == 1 and q['type'] == '多选':
            warnings.append(f'题号 {q["id"]}：题型写的是多选，但只有 1 个答案')

    return errors, warnings


JS_HEADER = '''/**
 * 题库数据文件
 * ============================================================
 * 格式说明（要换题、加题，照着下面这个结构改即可）：
 *
 *   {
 *     id: 1,                          // 题号，必须唯一
 *     q: "题干文本",                   // 题干
 *     type: "单选",                    // "单选" 或 "多选"（仅用于显示）
 *     options: ["选项A", "选项B", "选项C", "选项D"],
 *                                     // 选项文本，不要带 "A. " 前缀，界面会自动加
 *     answer: [1],                    // 正确选项的【下标】，从 0 开始：
 *                                     //   A=0  B=1  C=2  D=3
 *                                     //   单选写 [1]；多选写 [0, 2, 3]
 *     explain: "解析文本"              // 可选，不写就不显示解析区
 *   }
 *
 * 判题规则：选中集合与 answer 完全一致才算对（多选少选、多选都算错）。
 * ============================================================
 */

const QUESTIONS = [
'''


def render_js(questions):
    """渲染成 questions.js 的内容"""
    lines = []
    for q in questions:
        opts = ', '.join(json.dumps(o, ensure_ascii=False) for o in q['options'])
        ans = ', '.join(str(i) for i in sorted(set(q['answer'])))
        parts = [
            '  { id: %d' % q['id'],
            'q: %s' % json.dumps(q['q'], ensure_ascii=False),
            'type: %s' % json.dumps(q['type'], ensure_ascii=False),
            'options: [%s]' % opts,
            'answer: [%s]' % ans,
        ]
        if q['explain']:
            parts.append('explain: %s' % json.dumps(q['explain'], ensure_ascii=False))
        lines.append(', '.join(parts) + ' },')
    return JS_HEADER + '\n'.join(lines) + '\n];\n'


def main():
    ap = argparse.ArgumentParser(
        description='把纯文本题库转换成刷题应用的 questions.js',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='源文件格式说明见本脚本头部的注释。')
    ap.add_argument('src', help='源题库文件，UTF-8 编码的 .txt')
    ap.add_argument('-o', '--out', default='questions.js',
                    help='输出的 JS 文件路径（默认 questions.js）')
    ap.add_argument('-q', '--quiet', action='store_true', help='只输出错误，不打印统计')
    args = ap.parse_args()

    if not Path(args.src).exists():
        print(f'找不到源文件：{args.src}', file=sys.stderr)
        return 1

    questions, parse_warnings = parse(args.src)
    errors, validate_warnings = validate(questions)
    warnings = parse_warnings + validate_warnings

    if errors:
        print('转换失败，发现以下问题：\n', file=sys.stderr)
        for e in errors:
            print('  ✘ ' + e, file=sys.stderr)
        if warnings:
            print('\n另外还有 %d 条警告。' % len(warnings), file=sys.stderr)
        return 1

    Path(args.out).write_text(render_js(questions), encoding='utf-8')

    if not args.quiet:
        solo = sum(1 for q in questions if len(q['answer']) == 1)
        with_tip = sum(1 for q in questions if q['explain'])
        print('题目总数: %d  （单选 %d / 多选 %d）' % (len(questions), solo, len(questions) - solo))
        print('带解析的: %d' % with_tip)
        print('题号范围: %d - %d' % (min(q['id'] for q in questions),
                                    max(q['id'] for q in questions)))
        if warnings:
            print('\n%d 条警告：' % len(warnings))
            for w in warnings[:20]:
                print('  ! ' + w)
            if len(warnings) > 20:
                print('  ... 还有 %d 条' % (len(warnings) - 20))
        print('\n已生成: %s' % Path(args.out).resolve())

    return 0


if __name__ == '__main__':
    sys.exit(main())
