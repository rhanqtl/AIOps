package com.aiops.processdata.po.span;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

/**
 * @author Zongwen Yang
 * @version 1.0
 * @date 2020/4/15 16:19
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class LogPO {
    private Integer entityId;
    private Date time;
    private Integer spanId;
    private String data;
}
