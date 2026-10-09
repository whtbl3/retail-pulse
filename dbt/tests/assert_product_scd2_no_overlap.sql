SELECT p1.product_id, p1.valid_from AS p1_from, p1.valid_to AS p1_to, p2.valid_from AS p2_from
FROM {{ ref('int_product_scd2') }} p1
JOIN {{ ref('int_product_scd2') }} p2
  ON p1.product_id = p2.product_id
 AND p1.valid_from < p2.valid_from
 AND p1.valid_to   > p2.valid_from