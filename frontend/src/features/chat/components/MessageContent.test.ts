import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MessageContent from './MessageContent.vue'

describe('MessageContent', () => {
  it('renders Markdown without interpreting model-provided HTML', () => {
    const wrapper = mount(MessageContent, {
      props: {
        content: '# 结果\n\n- **已修复**问题\n- 已运行 `pytest`\n\n<img src=x onerror=alert(1)>',
      },
    })

    expect(wrapper.get('h1').text()).toBe('结果')
    expect(wrapper.findAll('li')).toHaveLength(2)
    expect(wrapper.get('strong').text()).toBe('已修复')
    expect(wrapper.get('li code').text()).toBe('pytest')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  })

  it('formats tables and nested lists for technical answers', () => {
    const wrapper = mount(MessageContent, {
      props: {
        content: '| 检查 | 结果 |\n| --- | --- |\n| 类型检查 | 通过 |\n\n1. 修改代码\n   - 保留兼容性',
      },
    })

    expect(wrapper.findAll('th')).toHaveLength(2)
    expect(wrapper.get('td').text()).toBe('类型检查')
    expect(wrapper.find('ol ul').exists()).toBe(true)
  })

  it('separates fenced code from explanatory text', () => {
    const wrapper = mount(MessageContent, {
      props: { content: '运行：\n\n```bash\npython -m pytest -q\n```' },
    })

    expect(wrapper.get('.code-toolbar').text()).toContain('bash')
    expect(wrapper.get('code').text()).toBe('python -m pytest -q')
    expect(wrapper.get('button').attributes('aria-label')).toBe('复制代码')
  })

  it('does not create executable links or load model-provided images', () => {
    const wrapper = mount(MessageContent, {
      props: {
        content: '[危险链接](javascript:alert(1))\n\n![远程图片](https://example.com/a.png)',
      },
    })

    expect(wrapper.find('a[href^="javascript:"]').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('图片引用：远程图片')
  })
})
